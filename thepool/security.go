package main

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"crypto/tls"
	"encoding/hex"
	"net/http"
	"net/url"
	"regexp"
	"sync"
	"time"
	"unicode/utf8"
)

type oauthBinding struct {
	expires time.Time
	code    [32]byte
}

var oauthMutex sync.Mutex
var oauthFlows = map[string]oauthBinding{}
var oauthCodes = map[string]oauthBinding{}

const flowCookie = "thepool_oauth_state"
const codeCookie = "thepool_oauth_code"
const flowLifetime = 10 * time.Minute

var nativeChunkIDs = regexp.MustCompile(`^[A-Za-z0-9]+$`)

func init() { httpClient.Timeout = 30 * time.Second }

// Kubernetes rotates the fresh TLS Secret atomically; new handshakes reload it.
func reloadBackendCertificate(_ *tls.ClientHelloInfo) (*tls.Certificate, error) {
	certificate, err := tls.LoadX509KeyPair(WEBSERVER_TLS_CERT_PATH, WEBSERVER_TLS_KEY_PATH)
	if err != nil {
		return nil, err
	}
	return &certificate, nil
}

func freshOAuthNonce() string {
	var bytes [32]byte
	if _, err := rand.Read(bytes[:]); err != nil {
		panic("OAuth entropy unavailable")
	}
	return hex.EncodeToString(bytes[:])
}

func pruneOAuth(entries map[string]oauthBinding) {
	for key, binding := range entries {
		if time.Now().After(binding.expires) {
			delete(entries, key)
		}
	}
}

func oauthCookie(w http.ResponseWriter, name, value, path string, maxAge int) {
	http.SetCookie(w, &http.Cookie{Name: name, Value: value, Path: path, HttpOnly: true, Secure: true, SameSite: http.SameSiteLaxMode, MaxAge: maxAge})
}

func secureAuthenticationLink(w http.ResponseWriter, r *http.Request) string {
	u, err := url.Parse(createAuthenticationLink())
	if err != nil {
		return ""
	}
	if !DISCORD_AUTH_ENABLED {
		return u.String()
	}
	oauthMutex.Lock()
	defer oauthMutex.Unlock()
	pruneOAuth(oauthFlows)
	if len(oauthFlows) >= 4096 {
		return ""
	}
	state := freshOAuthNonce()
	oauthFlows[state] = oauthBinding{expires: time.Now().Add(flowLifetime)}
	q := u.Query()
	q.Set("state", state)
	u.RawQuery = q.Encode()
	oauthCookie(w, flowCookie, state, "/auth/callback", 600)
	w.Header().Set("Cache-Control", "no-store")
	return u.String()
}

func verifyOAuthCallback(w http.ResponseWriter, r *http.Request) bool {
	state := r.URL.Query().Get("state")
	cookie, err := r.Cookie(flowCookie)
	if err != nil || len(state) != 64 || subtle.ConstantTimeCompare([]byte(cookie.Value), []byte(state)) != 1 {
		http.Error(w, "Invalid OAuth browser state", http.StatusForbidden)
		return false
	}
	if issuer := r.URL.Query().Get("iss"); issuer != "" && issuer != "https://discord.com" {
		http.Error(w, "Invalid OAuth issuer", http.StatusForbidden)
		return false
	}
	oauthMutex.Lock()
	defer oauthMutex.Unlock()
	binding, exists := oauthFlows[state]
	delete(oauthFlows, state)
	if !exists || time.Now().After(binding.expires) {
		http.Error(w, "Expired OAuth state", http.StatusForbidden)
		return false
	}
	oauthCookie(w, flowCookie, "", "/auth/callback", -1)
	code := r.URL.Query().Get("code")
	if code == "" {
		return true
	} // Keep native cancellation/error page behavior.
	if len(code) > 2048 {
		http.Error(w, "Invalid OAuth code", http.StatusBadRequest)
		return false
	}
	pruneOAuth(oauthCodes)
	if len(oauthCodes) >= 4096 {
		http.Error(w, "OAuth capacity exceeded", http.StatusTooManyRequests)
		return false
	}
	nonce := freshOAuthNonce()
	oauthCodes[nonce] = oauthBinding{expires: time.Now().Add(flowLifetime), code: sha256.Sum256([]byte(code))}
	oauthCookie(w, codeCookie, nonce, "/api/token/", 600)
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Referrer-Policy", "no-referrer")
	return true
}

func consumeOAuthCode(w http.ResponseWriter, r *http.Request, code string) bool {
	cookie, err := r.Cookie(codeCookie)
	if err != nil {
		http.Error(w, "OAuth browser binding required", http.StatusForbidden)
		return false
	}
	oauthMutex.Lock()
	defer oauthMutex.Unlock()
	binding, exists := oauthCodes[cookie.Value]
	delete(oauthCodes, cookie.Value)
	hash := sha256.Sum256([]byte(code))
	if !exists || time.Now().After(binding.expires) || subtle.ConstantTimeCompare(hash[:], binding.code[:]) != 1 {
		http.Error(w, "Invalid OAuth code binding", http.StatusForbidden)
		return false
	}
	oauthCookie(w, codeCookie, "", "/api/token/", -1)
	w.Header().Set("Cache-Control", "no-store")
	return true
}

func validCollectionInput(collection Collection) bool {
	return utf8.ValidString(collection.OriginalName) && utf8.RuneCountInString(collection.OriginalName) <= 255 &&
		utf8.ValidString(collection.MimeType) && utf8.RuneCountInString(collection.MimeType) <= 255 &&
		len(collection.ChunkIds) > 0 && len(collection.ChunkIds) <= 10000 && len(collection.ChunkIds)%10 == 0 && nativeChunkIDs.MatchString(collection.ChunkIds)
}
