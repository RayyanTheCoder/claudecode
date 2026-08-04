#!/usr/bin/env bash
# Cross-compiles VidGrab to a single Windows .exe from any platform with Go installed.
set -euo pipefail
cd "$(dirname "$0")"

go vet ./...
go test ./...

GOOS=windows GOARCH=amd64 go build -ldflags "-s -w" -o VidGrab.exe .

echo "Built VidGrab.exe ($(du -h VidGrab.exe | cut -f1))"
