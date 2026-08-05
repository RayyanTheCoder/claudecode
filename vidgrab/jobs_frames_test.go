package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// These tests exercise runFramesJob's orchestration (status transitions,
// frame sorting, source-video cleanup) against fake yt-dlp/ffmpeg shell
// scripts, without needing the real binaries or network access.

func writeFakeScript(t *testing.T, path, body string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(body), 0o755); err != nil {
		t.Fatalf("write fake script %s: %v", path, err)
	}
}

func TestRunFramesJob_EndToEnd(t *testing.T) {
	dir := t.TempDir()

	videoPath := filepath.Join(dir, "source.mp4")
	t.Setenv("FAKE_VIDEO_PATH", videoPath)

	ytDlp := filepath.Join(dir, "yt-dlp")
	writeFakeScript(t, ytDlp, "#!/bin/bash\n"+
		"echo '[download]  50.0% of 1.00MiB'\n"+
		"touch \"$FAKE_VIDEO_PATH\"\n"+
		"echo \"$FAKE_VIDEO_PATH\"\n"+
		"exit 0\n")

	ffmpeg := filepath.Join(dir, "ffmpeg")
	writeFakeScript(t, ffmpeg, "#!/bin/bash\n"+
		"last=\"${@: -1}\"\n"+
		"d=$(dirname \"$last\")\n"+
		"mkdir -p \"$d\"\n"+
		"touch \"$d/frame_0003.jpg\" \"$d/frame_0001.jpg\" \"$d/frame_0002.jpg\"\n"+
		"exit 0\n")

	frameDir := filepath.Join(dir, "frames")
	j := &Job{ID: "test", Status: "running"}
	runFramesJob(j, ytDlp, []string{"--fake"}, dir, ffmpeg, frameDir)

	snap := j.snapshot()
	if snap.Status != "done" {
		t.Fatalf("expected status done, got %q (err=%s, message=%s)", snap.Status, snap.Err, snap.Message)
	}

	want := []string{"frame_0001.jpg", "frame_0002.jpg", "frame_0003.jpg"}
	if len(snap.Frames) != len(want) {
		t.Fatalf("expected %d frames, got %v", len(want), snap.Frames)
	}
	for i, w := range want {
		if snap.Frames[i] != w {
			t.Errorf("frames[%d] = %q, want %q (frames should be sorted)", i, snap.Frames[i], w)
		}
	}

	if _, err := os.Stat(videoPath); !os.IsNotExist(err) {
		t.Errorf("expected source video to be removed after extraction, stat err = %v", err)
	}
}

func TestRunFramesJob_YtDlpFailure(t *testing.T) {
	dir := t.TempDir()

	ytDlp := filepath.Join(dir, "yt-dlp")
	writeFakeScript(t, ytDlp, "#!/bin/bash\necho 'boom' >&2\nexit 1\n")
	ffmpeg := filepath.Join(dir, "ffmpeg") // must never be invoked

	j := &Job{ID: "test", Status: "running"}
	runFramesJob(j, ytDlp, []string{"--fake"}, dir, ffmpeg, filepath.Join(dir, "frames"))

	snap := j.snapshot()
	if snap.Status != "error" {
		t.Fatalf("expected status error when yt-dlp fails, got %q", snap.Status)
	}
	if len(snap.Frames) != 0 {
		t.Errorf("expected no frames on yt-dlp failure, got %v", snap.Frames)
	}
}

func TestRunFramesJob_FFmpegFailure(t *testing.T) {
	dir := t.TempDir()

	videoPath := filepath.Join(dir, "source.mp4")
	t.Setenv("FAKE_VIDEO_PATH", videoPath)

	ytDlp := filepath.Join(dir, "yt-dlp")
	writeFakeScript(t, ytDlp, "#!/bin/bash\n"+
		"touch \"$FAKE_VIDEO_PATH\"\n"+
		"echo \"$FAKE_VIDEO_PATH\"\n"+
		"exit 0\n")

	ffmpeg := filepath.Join(dir, "ffmpeg")
	writeFakeScript(t, ffmpeg, "#!/bin/bash\necho 'ffmpeg exploded' >&2\nexit 1\n")

	j := &Job{ID: "test", Status: "running"}
	runFramesJob(j, ytDlp, []string{"--fake"}, dir, ffmpeg, filepath.Join(dir, "frames"))

	snap := j.snapshot()
	if snap.Status != "error" {
		t.Fatalf("expected status error when ffmpeg fails, got %q", snap.Status)
	}
}

func TestEnvWithBinDirOnPath_NoDuplicatePathKeys(t *testing.T) {
	env := envWithBinDirOnPath("/fake/bin")

	pathCount := 0
	var pathValue string
	for _, kv := range env {
		key, value, ok := strings.Cut(kv, "=")
		if ok && strings.EqualFold(key, "PATH") {
			pathCount++
			pathValue = value
		}
	}

	if pathCount != 1 {
		t.Fatalf("expected exactly one PATH entry, found %d in %v", pathCount, env)
	}
	if !strings.HasPrefix(pathValue, "/fake/bin") {
		t.Errorf("expected PATH to start with /fake/bin, got %q", pathValue)
	}
}
