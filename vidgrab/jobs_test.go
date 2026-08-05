package main

import (
	"strings"
	"testing"
)

func contains(args []string, want string) bool {
	for _, a := range args {
		if a == want {
			return true
		}
	}
	return false
}

func flagValue(args []string, flag string) (string, bool) {
	for i, a := range args {
		if a == flag && i+1 < len(args) {
			return args[i+1], true
		}
	}
	return "", false
}

func TestBuildYtDlpArgs_VideoAudioBest(t *testing.T) {
	args, err := buildYtDlpArgs("https://youtube.com/watch?v=x", ModeVideoAudio, "best", "C:\\bin", "C:\\out\\%(title)s.%(ext)s", false)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	f, ok := flagValue(args, "-f")
	if !ok {
		t.Fatalf("missing -f flag in %v", args)
	}
	if f != "bestvideo+bestaudio/best" {
		t.Errorf("unexpected format selector: %q", f)
	}
	if !contains(args, "--merge-output-format") {
		t.Errorf("expected merge-output-format for video+audio mode")
	}
	if strings.Contains(f, "height") {
		t.Errorf("best quality should not filter by height, got %q", f)
	}
}

func TestBuildYtDlpArgs_VideoAudio1080p(t *testing.T) {
	args, err := buildYtDlpArgs("https://tiktok.com/@a/video/1", ModeVideoAudio, "1080", "bin", "out", false)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	f, _ := flagValue(args, "-f")
	want := "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
	if f != want {
		t.Errorf("got %q, want %q", f, want)
	}
}

func TestBuildYtDlpArgs_VideoOnly(t *testing.T) {
	args, err := buildYtDlpArgs("https://instagram.com/reel/x", ModeVideoOnly, "720", "bin", "out", false)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	f, _ := flagValue(args, "-f")
	if f != "bestvideo[height<=720]" {
		t.Errorf("unexpected format selector: %q", f)
	}
	if contains(args, "bestaudio") {
		t.Errorf("video-only mode should not request an audio stream, got %v", args)
	}
}

func TestBuildYtDlpArgs_AudioOnly(t *testing.T) {
	args, err := buildYtDlpArgs("https://youtu.be/x", ModeAudioOnly, "best", "bin", "out", false)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !contains(args, "-x") {
		t.Errorf("expected -x (extract audio) flag, got %v", args)
	}
	af, ok := flagValue(args, "--audio-format")
	if !ok || af != "mp3" {
		t.Errorf("expected --audio-format mp3, got %v", args)
	}
	if contains(args, "--merge-output-format") {
		t.Errorf("audio-only mode should not merge video+audio, got %v", args)
	}
}

func TestBuildYtDlpArgs_Frames(t *testing.T) {
	args, err := buildYtDlpArgs("https://youtube.com/watch?v=x", ModeFrames, "1080", "bin", "out", false)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	f, _ := flagValue(args, "-f")
	if f != "bestvideo[height<=1080]" {
		t.Errorf("unexpected format selector: %q", f)
	}
	if contains(args, "bestaudio") {
		t.Errorf("frames mode should not request an audio stream, got %v", args)
	}
}

func TestBuildYtDlpArgs_RejectsEmptyURL(t *testing.T) {
	if _, err := buildYtDlpArgs("", ModeVideoAudio, "best", "bin", "out", false); err == nil {
		t.Errorf("expected error for empty URL")
	}
}

func TestBuildYtDlpArgs_RejectsBadQuality(t *testing.T) {
	if _, err := buildYtDlpArgs("https://youtube.com/x", ModeVideoAudio, "9999", "bin", "out", false); err == nil {
		t.Errorf("expected error for invalid quality")
	}
}

func TestBuildYtDlpArgs_RejectsBadMode(t *testing.T) {
	if _, err := buildYtDlpArgs("https://youtube.com/x", Mode("bogus"), "best", "bin", "out", false); err == nil {
		t.Errorf("expected error for invalid mode")
	}
}

func TestBuildYtDlpArgs_URLIsLastArg(t *testing.T) {
	url := "https://www.youtube.com/watch?v=abc123"
	args, err := buildYtDlpArgs(url, ModeVideoAudio, "best", "bin", "out", false)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if args[len(args)-1] != url {
		t.Errorf("expected URL as last argument, got %v", args)
	}
}

func TestBuildYtDlpArgs_AlwaysSetsConcurrentFragments(t *testing.T) {
	for _, useAria2 := range []bool{false, true} {
		args, err := buildYtDlpArgs("https://youtube.com/x", ModeVideoAudio, "best", "bin", "out", useAria2)
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if v, ok := flagValue(args, "--concurrent-fragments"); !ok || v != "8" {
			t.Errorf("useAria2=%v: expected --concurrent-fragments 8, got %v", useAria2, args)
		}
	}
}

func TestBuildYtDlpArgs_Aria2Toggle(t *testing.T) {
	withoutAria2, err := buildYtDlpArgs("https://youtube.com/x", ModeVideoAudio, "best", "bin", "out", false)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if contains(withoutAria2, "--downloader") {
		t.Errorf("useAria2=false should not set --downloader, got %v", withoutAria2)
	}

	withAria2, err := buildYtDlpArgs("https://youtube.com/x", ModeVideoAudio, "best", "bin", "out", true)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	dl, ok := flagValue(withAria2, "--downloader")
	if !ok || dl != "aria2c" {
		t.Errorf("useAria2=true: expected --downloader aria2c, got %v", withAria2)
	}
	if _, ok := flagValue(withAria2, "--downloader-args"); !ok {
		t.Errorf("useAria2=true: expected --downloader-args to be set, got %v", withAria2)
	}
}

func TestFilePathLineRegex(t *testing.T) {
	cases := map[string]bool{
		`C:\Users\me\Downloads\VidGrab\My Video [abc123].mp4`:     true,
		`[download]  45.2% of   10.00MiB at  1.20MiB/s ETA 00:05`: false,
		`[Merger] Merging formats into "video.mp4"`:               false,
	}
	for line, want := range cases {
		got := filePathLine.MatchString(line)
		if got != want {
			t.Errorf("filePathLine.MatchString(%q) = %v, want %v", line, got, want)
		}
	}
}

func TestPercentRegex(t *testing.T) {
	m := percentRe.FindStringSubmatch("[download]  45.2% of   10.00MiB at  1.20MiB/s ETA 00:05")
	if m == nil || m[1] != "45.2" {
		t.Errorf("expected to parse 45.2, got %v", m)
	}
}
