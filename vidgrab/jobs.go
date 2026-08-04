package main

import (
	"bufio"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"os"
	"os/exec"
	"regexp"
	"sync"
)

// Mode selects what streams to keep.
type Mode string

const (
	ModeVideoAudio Mode = "video_audio"
	ModeVideoOnly  Mode = "video_only"
	ModeAudioOnly  Mode = "audio_only"
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
	case ModeVideoOnly:
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

// Job tracks the state of a single download.
type Job struct {
	mu       sync.Mutex
	ID       string
	Status   string // "running", "done", "error"
	Message  string // last line of yt-dlp output shown to the user
	Percent  float64
	FilePath string
	Err      string
}

// JobSnapshot is a point-in-time, lock-free copy of a Job safe to marshal or pass around.
type JobSnapshot struct {
	ID       string  `json:"id"`
	Status   string  `json:"status"`
	Message  string  `json:"message"`
	Percent  float64 `json:"percent"`
	FilePath string  `json:"filePath"`
	Err      string  `json:"err"`
}

func (j *Job) snapshot() JobSnapshot {
	j.mu.Lock()
	defer j.mu.Unlock()
	return JobSnapshot{
		ID: j.ID, Status: j.Status, Message: j.Message,
		Percent: j.Percent, FilePath: j.FilePath, Err: j.Err,
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

// runJob executes yt-dlp for the given job. binDir is prepended to PATH so that
// yt-dlp's shelled-out call to "aria2c" (if used) resolves to our bundled copy.
func runJob(j *Job, ytDlpPath string, args []string, binDir string) {
	cmd := exec.Command(ytDlpPath, args...)
	cmd.Env = append(os.Environ(), "PATH="+binDir+string(os.PathListSeparator)+os.Getenv("PATH"))
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		failJob(j, err.Error())
		return
	}
	cmd.Stderr = cmd.Stdout

	if err := cmd.Start(); err != nil {
		failJob(j, err.Error())
		return
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

	err = cmd.Wait()

	j.mu.Lock()
	defer j.mu.Unlock()
	if err != nil {
		j.Status = "error"
		j.Err = err.Error()
		return
	}
	j.Status = "done"
	j.Percent = 100
	j.FilePath = lastFilePath
}

func failJob(j *Job, msg string) {
	j.mu.Lock()
	defer j.mu.Unlock()
	j.Status = "error"
	j.Err = msg
}
