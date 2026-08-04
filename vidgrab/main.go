package main

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"time"
)

//go:embed web/index.html
var indexHTML []byte

const port = "8991"

func main() {
	exePath, err := os.Executable()
	if err != nil {
		log.Fatalf("cannot locate executable: %v", err)
	}
	baseDir := filepath.Dir(exePath)
	binDir := filepath.Join(baseDir, "bin")

	downloadsDir := defaultDownloadsDir(baseDir)
	if err := os.MkdirAll(downloadsDir, 0o755); err != nil {
		log.Fatalf("cannot create downloads folder: %v", err)
	}

	ytDlpPath, err := ensureYtDlp(binDir)
	if err != nil {
		log.Fatalf("could not set up yt-dlp: %v", err)
	}
	ffmpegDir, err := ensureFFmpeg(binDir)
	if err != nil {
		log.Fatalf("could not set up ffmpeg: %v", err)
	}
	fmt.Println("Ready. Downloads will be saved to:", downloadsDir)

	store := newJobStore()
	outputTemplate := filepath.Join(downloadsDir, "%(title).200B [%(id)s].%(ext)s")

	mux := http.NewServeMux()

	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = w.Write(indexHTML)
	})

	mux.HandleFunc("/api/download", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var req struct {
			URL     string `json:"url"`
			Mode    string `json:"mode"`
			Quality string `json:"quality"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}

		args, err := buildYtDlpArgs(req.URL, Mode(req.Mode), req.Quality, ffmpegDir, outputTemplate)
		if err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}

		job := store.create()
		go runJob(job, ytDlpPath, args)

		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]string{"id": job.ID})
	})

	mux.HandleFunc("/api/progress", func(w http.ResponseWriter, r *http.Request) {
		id := r.URL.Query().Get("id")
		job, ok := store.get(id)
		if !ok {
			http.Error(w, "unknown job", http.StatusNotFound)
			return
		}

		w.Header().Set("Content-Type", "text/event-stream")
		w.Header().Set("Cache-Control", "no-cache")
		flusher, ok := w.(http.Flusher)
		if !ok {
			http.Error(w, "streaming unsupported", http.StatusInternalServerError)
			return
		}

		for {
			snap := job.snapshot()
			data, _ := json.Marshal(snap)
			fmt.Fprintf(w, "data: %s\n\n", data)
			flusher.Flush()

			if snap.Status == "done" || snap.Status == "error" {
				return
			}
			select {
			case <-r.Context().Done():
				return
			case <-time.After(500 * time.Millisecond):
			}
		}
	})

	mux.HandleFunc("/api/open-folder", func(w http.ResponseWriter, r *http.Request) {
		id := r.URL.Query().Get("id")
		job, ok := store.get(id)
		if !ok {
			http.Error(w, "unknown job", http.StatusNotFound)
			return
		}
		snap := job.snapshot()
		if snap.FilePath != "" {
			openInFileManager(snap.FilePath)
		} else {
			openInFileManager(downloadsDir)
		}
		w.WriteHeader(http.StatusNoContent)
	})

	addr := "127.0.0.1:" + port
	url := "http://" + addr

	go func() {
		time.Sleep(400 * time.Millisecond)
		openBrowser(url)
	}()

	fmt.Println("VidGrab running at", url)
	log.Fatal(http.ListenAndServe(addr, mux))
}

func defaultDownloadsDir(baseDir string) string {
	if profile := os.Getenv("USERPROFILE"); profile != "" {
		return filepath.Join(profile, "Downloads", "VidGrab")
	}
	if home, err := os.UserHomeDir(); err == nil && home != "" {
		return filepath.Join(home, "Downloads", "VidGrab")
	}
	return filepath.Join(baseDir, "downloads")
}

func openBrowser(url string) {
	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "windows":
		cmd = exec.Command("rundll32", "url.dll,FileProtocolHandler", url)
	case "darwin":
		cmd = exec.Command("open", url)
	default:
		cmd = exec.Command("xdg-open", url)
	}
	_ = cmd.Start()
}

func openInFileManager(path string) {
	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "windows":
		cmd = exec.Command("explorer", "/select,"+path)
	case "darwin":
		cmd = exec.Command("open", "-R", path)
	default:
		cmd = exec.Command("xdg-open", filepath.Dir(path))
	}
	_ = cmd.Start()
}
