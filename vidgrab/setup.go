package main

import (
	"archive/zip"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const (
	ytDlpURL     = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
	ffmpegZipURL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
)

var httpClient = &http.Client{Timeout: 20 * time.Minute}

// ensureYtDlp makes sure yt-dlp.exe exists under binDir, downloading it if needed.
func ensureYtDlp(binDir string) (string, error) {
	dst := filepath.Join(binDir, "yt-dlp.exe")
	if fileExists(dst) {
		return dst, nil
	}
	fmt.Println("Downloading yt-dlp (one-time setup)...")
	if err := downloadFile(ytDlpURL, dst); err != nil {
		return "", fmt.Errorf("download yt-dlp: %w", err)
	}
	return dst, nil
}

// ensureFFmpeg makes sure ffmpeg.exe and ffprobe.exe exist under binDir, downloading them if needed.
func ensureFFmpeg(binDir string) (string, error) {
	ffmpegPath := filepath.Join(binDir, "ffmpeg.exe")
	ffprobePath := filepath.Join(binDir, "ffprobe.exe")
	if fileExists(ffmpegPath) && fileExists(ffprobePath) {
		return binDir, nil
	}

	fmt.Println("Downloading ffmpeg (one-time setup, ~80MB)...")
	tmpZip := filepath.Join(os.TempDir(), "vidgrab-ffmpeg.zip")
	defer os.Remove(tmpZip)

	if err := downloadFile(ffmpegZipURL, tmpZip); err != nil {
		return "", fmt.Errorf("download ffmpeg: %w", err)
	}

	if err := extractFromZip(tmpZip, "ffmpeg.exe", ffmpegPath); err != nil {
		return "", fmt.Errorf("extract ffmpeg.exe: %w", err)
	}
	if err := extractFromZip(tmpZip, "ffprobe.exe", ffprobePath); err != nil {
		return "", fmt.Errorf("extract ffprobe.exe: %w", err)
	}
	return binDir, nil
}

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}

func downloadFile(url, dst string) error {
	resp, err := httpClient.Get(url)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("unexpected status %s", resp.Status)
	}

	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return err
	}
	tmp := dst + ".part"
	out, err := os.Create(tmp)
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, resp.Body); err != nil {
		out.Close()
		os.Remove(tmp)
		return err
	}
	out.Close()
	return os.Rename(tmp, dst)
}

// extractFromZip finds the first entry in zipPath whose base name matches wantName
// (case-insensitive) and writes it to dst.
func extractFromZip(zipPath, wantName, dst string) error {
	r, err := zip.OpenReader(zipPath)
	if err != nil {
		return err
	}
	defer r.Close()

	want := strings.ToLower(wantName)
	for _, f := range r.File {
		if strings.ToLower(filepath.Base(f.Name)) != want {
			continue
		}
		rc, err := f.Open()
		if err != nil {
			return err
		}
		defer rc.Close()

		if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
			return err
		}
		out, err := os.Create(dst)
		if err != nil {
			return err
		}
		defer out.Close()

		_, err = io.Copy(out, rc)
		return err
	}
	return errors.New("not found in archive: " + wantName)
}
