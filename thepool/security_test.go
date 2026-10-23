package main

import (
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
)

func TestOAuthBrowserBindingAndOneUse(t *testing.T) {
	DISCORD_AUTH_ENABLED = true
	w := httptest.NewRecorder()
	link, _ := url.Parse(secureAuthenticationLink(w, httptest.NewRequest("GET", "/api/config", nil)))
	state := link.Query().Get("state")
	if len(state) != 64 {
		t.Fatal("Missing random state")
	}
	flow := w.Result().Cookies()[0]
	if !flow.Secure || !flow.HttpOnly || flow.SameSite != http.SameSiteLaxMode {
		t.Fatal("Unsafe flow cookie")
	}
	r := httptest.NewRequest("GET", "/auth/callback?state="+state+"&code=unit-only", nil)
	r.AddCookie(flow)
	bad := httptest.NewRecorder()
	if verifyOAuthCallback(bad, httptest.NewRequest("GET", r.URL.String(), nil)) {
		t.Fatal("Browser binding bypass")
	}
	callback := httptest.NewRecorder()
	if !verifyOAuthCallback(callback, r) {
		t.Fatal("Valid flow denied")
	}
	var code *http.Cookie
	for _, c := range callback.Result().Cookies() {
		if c.Name == codeCookie {
			code = c
		}
	}
	if code == nil {
		t.Fatal("Missing code binding")
	}
	exchange := httptest.NewRequest("GET", "/api/token/unit-only", nil)
	exchange.AddCookie(code)
	if !consumeOAuthCode(httptest.NewRecorder(), exchange, "unit-only") {
		t.Fatal("Valid code binding denied")
	}
	if consumeOAuthCode(httptest.NewRecorder(), exchange, "unit-only") {
		t.Fatal("Replay accepted")
	}
	if verifyOAuthCallback(httptest.NewRecorder(), r) {
		t.Fatal("State replay accepted")
	}
}

func TestCollectionShapeAndMissingChunkHeader(t *testing.T) {
	if !validCollectionInput(Collection{OriginalName: "기술 점검.txt", MimeType: "text/plain", ChunkIds: "abcdefghij"}) {
		t.Fatal("Native file shape rejected")
	}
	for _, value := range []string{"", "short", "abcdefghij'", strings.Repeat("a", 10010)} {
		if validCollectionInput(Collection{ChunkIds: value}) {
			t.Fatal("Malformed chunk IDs accepted")
		}
	}
	w := httptest.NewRecorder()
	r := httptest.NewRequest("POST", "/api/chunks", strings.NewReader("test"))
	r.Header.Set("Authorization", "Bearer "+getVaildToken())
	r.Header.Set("X-Thepool-Chunk-Order", "0")
	createChunkHandler.ServeHTTP(w, r)
	if w.Code != http.StatusBadRequest {
		t.Fatal("Missing size header must not panic or access storage")
	}
}
