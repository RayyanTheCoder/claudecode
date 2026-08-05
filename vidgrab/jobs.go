package main

import (
	"bufio"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
)

// Mode selects what streams to keep.
type Mode string

const (
	ModeVideoAudio Mode = "video_audio"
	ModeVideoOnly  Mode = "video_only"
	ModeAudioOnly  Mode = "audio_only"
	// ModeFrames downloads the video (no audio) and then splits it into one
	// JPEG per second via ffmpeg, instead of keeping the video file.
	ModeFrames Mode = "frames"
)

var validQualities = map[string]bool{
	"best": true, "2160": true, "1440": true, "1080": true, "720": true, "480": true,
}

// buildYtDlpArgs turns a user's mode/quality choice into yt-dlp CLI arguments.
// It is a pure function so it can be unit-tested without invoking yt-dlp.
// useAria2 enables aria2c as an external multi-connection downloader, which is
// the main lever for approaching a user's real line speed against CDNs that
// throttle single connections; --concurrent-fragments is always set as a free
// speedup even when aria2c isn't available.
func buildYtDlpArgs(rawURL string, mode Mode, quality, ffmpegDir, outputTemplate string, useAria2 bool) ([]string, error) {
	if rawURL == "" {
		return nil, fmt.Errorf("url is required")
	}
	if !validQualities[quality] {
		return nil, fmt.Errorf("unknown quality %q", quality)
	}

	heightFilter := ""
	if quality != "best" {
		heightFilter = "[height<=" + quality + "]"
	}

	args := []string{
		"--newline",
		"--no-playlist",
		"--concurrent-fragments", "8",
		"--ffmpeg-location", ffmpegDir,
		"-o", outputTemplate,
		"--print", "after_move:filepath",
	}
	if useAria2 {
		args = append(args,
			"--downloader", "aria2c",
			"--downloader-args", "aria2c:-x 16 -s 16 -k 1M",
		)
	}

	switch mode {
	case ModeVideoAudio:
		args = append(args,
			"-f", "bestvideo"+heightFilter+"+bestaudio/best"+heightFilter,
			"--merge-output-format", "mp4",
		)
	case ModeVideoOnly, ModeFrames:
		args = append(args,
			"-f", "bestvideo"+heightFilter,
			"--merge-output-format", "mp4",
		)
	case ModeAudioOnly:
		args = append(args,
			"-f", "bestaudio/best",
			"-x", "--audio-format", "mp3",
			"--audio-quality", "0",
		)
	default:
		return nil, fmt.Errorf("unknown mode %q", mode)
	}

	args = append(args, rawURL)
	return args, nil
}

// Job tracks the state of a single download (and, for frame jobs, the
// frame-extraction step that follows it).
type Job struct {
	mu       sync.Mutex
	ID       string
	Status   string // "running", "extracting" (frame jobs only), "done", "error"
	Message  string // last line of yt-dlp/ffmpeg output shown to the user
	Percent  float64
	FilePath string
	Frames   []string // extracted frame filenames, in order, for frame jobs
	Err      string
}

// JobSnapshot is a point-in-time, lock-free copy of a Job safe to marshal or pass around.
type JobSnapshot struct {
	ID       string   `json:"id"`
	Status   string   `json:"status"`
	Message  string   `json:"message"`
	Percent  float64  `json:"percent"`
	FilePath string   `json:"filePath"`
	Frames   []string `json:"frames,omitempty"`
	Err      string   `json:"err"`
}

func (j *Job) snapshot() JobSnapshot {
	j.mu.Lock()
	defer j.mu.Unlock()
	return JobSnapshot{
		ID: j.ID, Status: j.Status, Message: j.Message,
		Percent: j.Percent, FilePath: j.FilePath, Frames: j.Frames, Err: j.Err,
	}
}

type jobStore struct {
	mu   sync.Mutex
	jobs map[string]*Job
}

func newJobStore() *jobStore {
	return &jobStore{jobs: make(map[string]*Job)}
}

func (s *jobStore) get(id string) (*Job, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	j, ok := s.jobs[id]
	return j, ok
}

func (s *jobStore) create() *Job {
	id := randomID()
	j := &Job{ID: id, Status: "running"}
	s.mu.Lock()
	s.jobs[id] = j
	s.mu.Unlock()
	return j
}

func randomID() string {
	b := make([]byte, 8)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

var percentRe = regexp.MustCompile(`(\d+(?:\.\d+)?)%`)

// filePathLine matches non-progress, non-bracketed output lines emitted by
// --print after_move:filepath, which yt-dlp prints once the final file is in place.
var filePathLine = regexp.MustCompile(`^[^\[].*\.\w+$`)

// envWithBinDirOnPath returns the current environment with binDir prepended to
// PATH, with any existing PATH/Path entries removed first. A naive append of a
// second PATH= entry doesn't reliably win: most C runtimes' getenv (which is
// what a shelled-out child like aria2c would use to resolve itself) returns
// the first matching key in the environment block, not the last.
func envWithBinDirOnPath(binDir string) []string {
	base := os.Environ()
	out := make([]string, 0, len(base)+1)
	for _, kv := range base {
		if i := strings.IndexByte(kv, '='); i > 0 && strings.EqualFold(kv[:i], "PATH") {
			continue
		}
		out = append(out, kv)
	}
	return append(out, "PATH="+binDir+string(os.PathListSeparator)+os.Getenv("PATH"))
}

// runYtDlpDownload runs yt-dlp for the given job, streaming progress into it,
// and returns the final downloaded file's path. binDir is prepended to PATH so
// that yt-dlp's shelled-out call to "aria2c" (if used) resolves to our bundled
// copy. It updates j.Message/j.Percent as it goes but does not set j.Status —
// callers decide what "finished" means for their job type.
func runYtDlpDownload(j *Job, ytDlpPath string, args []string, binDir string) (string, error) {
	cmd := exec.Command(ytDlpPath, args...)
	cmd.Env = envWithBinDirOnPath(binDir)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return "", err
	}
	cmd.Stderr = cmd.Stdout

	if err := cmd.Start(); err != nil {
		return "", err
	}

	scanner := bufio.NewScanner(stdout)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	var lastFilePath string
	for scanner.Scan() {
		line := scanner.Text()

		j.mu.Lock()
		j.Message = line
		if m := percentRe.FindStringSubmatch(line); m != nil {
			var p float64
			_, _ = fmt.Sscanf(m[1], "%f", &p)
			j.Percent = p
		}
		j.mu.Unlock()

		if filePathLine.MatchString(line) {
			lastFilePath = line
		}
	}

	if err := cmd.Wait(); err != nil {
		return "", err
	}
	if lastFilePath == "" {
		return "", fmt.Errorf("yt-dlp did not report an output file")
	}
	return lastFilePath, nil
}

// runJob downloads a video/audio file for the given job.
func runJob(j *Job, ytDlpPath string, args []string, binDir string) {
	path, err := runYtDlpDownload(j, ytDlpPath, args, binDir)
	if err != nil {
		failJob(j, err.Error())
		return
	}

	j.mu.Lock()
	defer j.mu.Unlock()
	j.Status = "done"
	j.Percent = 100
	j.FilePath = path
}

// runFramesJob downloads a video for the given job, then splits it into one
// JPEG per second via ffmpeg into frameDir, deleting the source video
// afterward since only the frames are kept.
func runFramesJob(j *Job, ytDlpPath string, args []string, binDir, ffmpegExePath, frameDir string) {
	videoPath, err := runYtDlpDownload(j, ytDlpPath, args, binDir)
	if err != nil {
		failJob(j, err.Error())
		return
	}

	j.mu.Lock()
	j.Status = "extracting"
	j.Message = "Extracting one frame per second..."
	j.Percent = 95
	j.mu.Unlock()

	if err := os.MkdirAll(frameDir, 0o755); err != nil {
		failJob(j, err.Error())
		return
	}

	pattern := filepath.Join(frameDir, "frame_%04d.jpg")
	cmd := exec.Command(ffmpegExePath, "-y", "-i", videoPath, "-vf", "fps=1", "-q:v", "2", pattern)
	if out, err := cmd.CombinedOutput(); err != nil {
		failJob(j, "ffmpeg frame extraction failed: "+err.Error()+": "+string(out))
		return
	}
	_ = os.Remove(videoPath)

	entries, err := os.ReadDir(frameDir)
	if err != nil {
		failJob(j, err.Error())
		return
	}
	frames := make([]string, 0, len(entries))
	for _, e := range entries {
		if !e.IsDir() {
			frames = append(frames, e.Name())
		}
	}
	sort.Strings(frames)
	if len(frames) == 0 {
		failJob(j, "no frames were extracted")
		return
	}

	j.mu.Lock()
	defer j.mu.Unlock()
	j.Status = "done"
	j.Percent = 100
	j.Frames = frames
}

func failJob(j *Job, msg string) {
	j.mu.Lock()
	defer j.mu.Unlock()
	j.Status = "error"
	j.Err = msg
}
