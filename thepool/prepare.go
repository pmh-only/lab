// Hash-pinned native source overlay; never imports the image's bundled TLS key.
package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

func main() {
	if err := prepare(); err != nil {
		panic(err)
	}
}

func prepare() error {
	root := "/bootstrap"
	if len(os.Args) > 1 {
		root = os.Args[1]
	}
	dest := "/work/source"
	if len(os.Args) > 2 {
		dest = os.Args[2]
	}
	output := "/prepared"
	if len(os.Args) > 3 {
		output = os.Args[3]
	}
	var manifest struct {
		Repository, Commit string
		Files              map[string]string
	}
	b, err := os.ReadFile(filepath.Join(root, "source.json"))
	if err != nil {
		return err
	}
	if err = json.Unmarshal(b, &manifest); err != nil {
		return err
	}
	if manifest.Repository != "pmh-only/thepool" || len(manifest.Commit) != 40 {
		return fmt.Errorf("unreviewed source repository")
	}
	client := &http.Client{Timeout: 30 * time.Second}
	for name, digest := range manifest.Files {
		if filepath.Clean(name) != name || strings.Contains(name, "..") || filepath.IsAbs(name) {
			return fmt.Errorf("unsafe source path")
		}
		url := "https://raw.githubusercontent.com/" + manifest.Repository + "/" + manifest.Commit + "/" + name
		response, err := client.Get(url)
		if err != nil {
			return fmt.Errorf("pinned source download failed")
		}
		body, err := io.ReadAll(io.LimitReader(response.Body, 4<<20))
		response.Body.Close()
		if err != nil || response.StatusCode != 200 {
			return fmt.Errorf("pinned source HTTP error")
		}
		sum := sha256.Sum256(body)
		if hex.EncodeToString(sum[:]) != digest {
			return fmt.Errorf("pinned source hash differs: %s", name)
		}
		path := filepath.Join(dest, name)
		if err = os.MkdirAll(filepath.Dir(path), 0755); err != nil {
			return err
		}
		if err = os.WriteFile(path, body, 0644); err != nil {
			return err
		}
	}
	change := func(name, before, after string, count int) error {
		path := filepath.Join(dest, name)
		b, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		s := string(b)
		if strings.Count(s, before) != count {
			return fmt.Errorf("unreviewed native contract: %s", name)
		}
		return os.WriteFile(path, []byte(strings.ReplaceAll(s, before, after)), 0644)
	}
	patches := []struct {
		file, before, after string
		count               int
	}{
		{"web.go", "MinVersion: tls.VersionTLS12,", "MinVersion: tls.VersionTLS12,\n\t\tGetCertificate: reloadBackendCertificate,", 1},
		{"minio.go", "InsecureSkipVerify: true", "InsecureSkipVerify: false", 1},
		{"minio.go", "GovernanceBypass: true", "GovernanceBypass: false", 1},
		{"discord.go", `"data":            {accessToken}`, `"token":           {accessToken}`, 1},
		{"web_handlers.go", "\"fmt\"", "\"fmt\"\n\t\"html\"", 1},
		{"web_handlers.go", "var callbackViewHandler = httpLogFn(func(w http.ResponseWriter, r *http.Request) {", "var callbackViewHandler = httpLogFn(func(w http.ResponseWriter, r *http.Request) {\n\tif DISCORD_AUTH_ENABLED && !verifyOAuthCallback(w, r) { return }", 1},
		{"web_handlers.go", "\"authenticationLink\": createAuthenticationLink(),", "\"authenticationLink\": secureAuthenticationLink(w, r),", 1},
		{"web_handlers.go", "code := r.PathValue(\"code\")", "code := r.PathValue(\"code\")\n\tif DISCORD_AUTH_ENABLED && !consumeOAuthCode(w, r, code) { return }", 1},
		{"web_handlers.go", "chunkSizeRaw := r.Header[\"X-Thepool-Chunk-Size\"]\n\tif len(chunkOrderRaw) < 1", "chunkSizeRaw := r.Header[\"X-Thepool-Chunk-Size\"]\n\tif len(chunkSizeRaw) < 1", 1},
		{"web_handlers.go", "if err != nil || chunkOrder < 0", "if err != nil || chunkOrder < 0 || chunkOrder > 4294967295", 1},
		{"web_handlers.go", "payload.CollectionId = id", "if !validCollectionInput(payload) { writeJSON(w, http.StatusBadRequest, map[string]any{\"success\": false, \"message\": \"payload invalid\"}); return }\n\tpayload.CollectionId = id", 1},
		{"web_handlers.go", `"{{collection_id}}", id)`, `"{{collection_id}}", html.EscapeString(id))`, 1},
		{"web_handlers.go", `"{{file_name}}", collection.OriginalName)`, `"{{file_name}}", html.EscapeString(collection.OriginalName))`, 1},
		{"web_handlers.go", `"{{mime_type}}", fmt.Sprint(collection.MimeType))`, `"{{mime_type}}", html.EscapeString(collection.MimeType))`, 1},
		{"public/upload.js", "${file.name}", "${escapeHtml(file.name)}", 4},
		{"public/upload.js", "${err?.message ?? err}", "${escapeHtml(err?.message ?? err)}", 1},
		{"public/download.js", "${name}", "${escapeHtml(name)}", 3},
		{"public/download.js", "${collectionId}`)", "${escapeHtml(collectionId)}`)", 1},
		{"public/download.js", "${err?.message ?? err}", "${escapeHtml(err?.message ?? err)}", 1},
	}
	for _, p := range patches {
		if err = change(p.file, p.before, p.after, p.count); err != nil {
			return err
		}
	}
	common := filepath.Join(dest, "public/commons.js")
	b, err = os.ReadFile(common)
	if err != nil {
		return err
	}
	escape := "function escapeHtml(value) { return String(value).replace(/[&<>\"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c])) }\n"
	if err = os.WriteFile(common, append([]byte(escape), b...), 0644); err != nil {
		return err
	}
	if err = os.MkdirAll(output, 0755); err != nil {
		return err
	}
	for _, name := range []string{"security.go", "security_test.go", "storage_probe_test.go"} {
		b, err = os.ReadFile(filepath.Join(root, name))
		if err != nil {
			return err
		}
		if err = os.WriteFile(filepath.Join(dest, name), b, 0644); err != nil {
			return err
		}
	}
	for _, name := range []string{"commons.js", "upload.js", "download.js"} {
		b, err = os.ReadFile(filepath.Join(dest, "public", name))
		if err != nil {
			return err
		}
		path := filepath.Join(output, name)
		if existing, readErr := os.ReadFile(path); readErr == nil {
			if string(existing) != string(b) {
				return fmt.Errorf("existing prepared frontend differs")
			}
		} else if !os.IsNotExist(readErr) {
			return readErr
		} else if err = os.WriteFile(path, b, 0444); err != nil {
			return err
		}
	}
	fmt.Println("Pinned native source verified; original storage, retention, commands and frontend preserved with scoped safety fixes")
	return nil
}
