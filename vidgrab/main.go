package main

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"net/url"
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

	// yt-dlp writes here temporarily; finished files are served to the browser's
	// own download manager via /api/file. Wiped on every startup so it never
	// grows unbounded across runs.
	stagingDir := filepath.Join(baseDir, "tmp")
	_ = os.RemoveAll(stagingDir)
	if err := os.MkdirAll(stagingDir, 0o755); err != nil {
		log.Fatalf("cannot create staging folder: %v", err)
	}

	ytDlpPath, err := ensureYtDlp(binDir)
	if err != nil {
		log.Fatalf("could not set up yt-dlp: %v", err)
	}
	ffmpegDir, err := ensureFFmpeg(binDir)
	if err != nil {
		log.Fatalf("could not set up ffmpeg: %v", err)
	}
	useAria2, err := ensureAria2(binDir)
	if err != nil {
		fmt.Println("Note: faster downloads via aria2 aren't available this run, using standard speed:", err)
		useAria2 = false
	}
	fmt.Println("Ready.")

	store := newJobStore()
	outputTemplate := filepath.Join(stagingDir, "%(title).200B [%(id)s].%(ext)s")

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

		args, err := buildYtDlpArgs(req.URL, Mode(req.Mode), req.Quality, ffmpegDir, outputTemplate, useAria2)
		if err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}

		job := store.create()
		go runJob(job, ytDlpPath, args, binDir)

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

	// api/file hands a finished download to the browser's own download manager
	// (Content-Disposition: attachment) so it lands wherever the user's browser
	// is configured to save files, rather than a fixed folder we pick for them.
	mux.HandleFunc("/api/file", func(w http.ResponseWriter, r *http.Request) {
		id := r.URL.Query().Get("id")
		job, ok := store.get(id)
		if !ok {
			http.Error(w, "unknown job", http.StatusNotFound)
			return
		}
		snap := job.snapshot()
		if snap.Status != "done" || snap.FilePath == "" {
			http.Error(w, "file not ready", http.StatusConflict)
			return
		}

		w.Header().Set("Content-Disposition", contentDispositionHeader(filepath.Base(snap.FilePath)))
		http.ServeFile(w, r, snap.FilePath)
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

// contentDispositionHeader builds an attachment header that keeps browser
// compatibility (ASCII fallback filename) while still preserving the real,
// possibly non-ASCII, video title via the RFC 5987 filename* form.
func contentDispositionHeader(filename string) string {
	ascii := make([]rune, 0, len(filename))
	for _, r := range filename {
		if r >= 32 && r < 127 && r != '"' && r != '\\' {
			ascii = append(ascii, r)
		} else {
			ascii = append(ascii, '_')
		}
	}
	asciiName := string(ascii)
	if asciiName == "" {
		asciiName = "download"
	}
	return fmt.Sprintf(`attachment; filename="%s"; filename*=UTF-8''%s`, asciiName, url.PathEscape(filename))
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
