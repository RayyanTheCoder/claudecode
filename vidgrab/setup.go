package main

import (
	"archive/zip"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

const (
	ytDlpURL       = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
	ffmpegZipURL   = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
	aria2LatestAPI = "https://api.github.com/repos/aria2/aria2/releases/latest"
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

// ensureAria2 makes sure aria2c.exe exists under binDir, downloading it if needed.
// aria2c lets yt-dlp fetch a file over many parallel connections instead of one,
// which is the main lever for getting closer to a user's actual line speed against
// CDNs (like YouTube's) that throttle single connections. It's optional: on any
// failure this returns ok=false so the caller can fall back to the built-in downloader.
func ensureAria2(binDir string) (ok bool, err error) {
	dst := filepath.Join(binDir, "aria2c.exe")
	if fileExists(dst) {
		return true, nil
	}

	fmt.Println("Downloading aria2 (one-time setup, enables faster multi-connection downloads)...")
	assetURL, err := findAria2WindowsAssetURL()
	if err != nil {
		return false, fmt.Errorf("find aria2 release asset: %w", err)
	}

	tmpZip := filepath.Join(os.TempDir(), "vidgrab-aria2.zip")
	defer os.Remove(tmpZip)
	if err := downloadFile(assetURL, tmpZip); err != nil {
		return false, fmt.Errorf("download aria2: %w", err)
	}
	if err := extractFromZip(tmpZip, "aria2c.exe", dst); err != nil {
		return false, fmt.Errorf("extract aria2c.exe: %w", err)
	}
	return true, nil
}

type ghAsset struct {
	Name               string `json:"name"`
	BrowserDownloadURL string `json:"browser_download_url"`
}

type ghRelease struct {
	Assets []ghAsset `json:"assets"`
}

var aria2WindowsAssetRe = regexp.MustCompile(`(?i)win-64bit.*\.zip$`)

func findAria2WindowsAssetURL() (string, error) {
	req, err := http.NewRequest(http.MethodGet, aria2LatestAPI, nil)
	if err != nil {
		return "", err
	}
	req.Header.Set("Accept", "application/vnd.github+json")

	resp, err := httpClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("github api status %s", resp.Status)
	}

	var release ghRelease
	if err := json.NewDecoder(resp.Body).Decode(&release); err != nil {
		return "", err
	}
	for _, a := range release.Assets {
		if aria2WindowsAssetRe.MatchString(a.Name) {
			return a.BrowserDownloadURL, nil
		}
	}
	return "", errors.New("no win-64bit asset found in latest aria2 release")
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
