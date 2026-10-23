package main

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"net/http"
	"os"
	"testing"

	"github.com/minio/minio-go/v7"
)

// Explicit technical probe, never enabled during normal builds or application
// startup. Uses genuine service storage credentials, not a fabricated user JWT.
func TestNativeStorageProbe(t *testing.T) {
	if os.Getenv("THEPOOL_STORAGE_PROBE") != "1" {
		t.Skip("isolated storage probe only")
	}
	createMysqlConnection()
	createMinioConnection()
	ids := []string{randID(10), randID(10)}
	collectionID := randID(10)
	payloads := [][]byte{[]byte("thepool technical probe part one\n"), []byte("thepool technical probe part two\n")}
	fmt.Printf("Owned technical probe collection=%s chunks=%s,%s\n", collectionID, ids[0], ids[1])
	defer func() {
		if _, err := db.Exec("DELETE FROM collections WHERE collection_id=?", collectionID); err != nil {
			t.Error("Owned collection cleanup failed")
		}
		for _, id := range ids {
			if _, err := db.Exec("DELETE FROM chunks WHERE chunk_id=?", id); err != nil {
				t.Error("Owned chunk metadata cleanup failed")
			}
		}
		deleteChunks(ids)
		for _, id := range ids {
			_, err := minioClient.StatObject(context.Background(), MINIO_BUCKET_NAME, MINIO_BUCKET_KEY_PREFIX+id, minio.StatObjectOptions{})
			failure := minio.ToErrorResponse(err)
			if failure.StatusCode != 404 || (failure.Code != "NoSuchKey" && failure.Code != "NotFound" && failure.Code != "NoSuchObject") {
				t.Errorf("Owned S3 probe cleanup not verified: %s HTTP %d", failure.Code, failure.StatusCode)
			}
		}
	}()
	for index, id := range ids {
		if err := uploadChunk(id, int64(len(payloads[index])), bytes.NewReader(payloads[index])); err != nil {
			t.Fatal("Native S3 upload failed")
		}
		createChunk(id, int64(len(payloads[index])), int64(index))
	}
	createCollection(Collection{CollectionId: collectionID, OriginalName: "lab-technical-probe-" + collectionID + ".txt", MimeType: "text/plain", ChunkIds: ids[0] + ids[1]})
	collection := getCollection(collectionID)
	if collection == nil || len(collection.Chunks) != 2 || collection.TotalSize != int64(len(payloads[0])+len(payloads[1])) {
		t.Fatal("Native collection assembly failed")
	}
	for index, chunk := range collection.Chunks {
		if chunk.ChunkId != ids[index] {
			t.Fatal("Native chunk ordering differs")
		}
		request, _ := http.NewRequest("GET", WEBSERVER_STATIC_ENDPOINT_PREFIX+"/"+chunk.ChunkId, nil)
		request.Header.Set("Origin", "https://pool.pmh.codes")
		response, err := httpClient.Do(request)
		if err != nil {
			t.Fatal("Public native download request failed")
		}
		body, err := io.ReadAll(response.Body)
		response.Body.Close()
		if err != nil || response.StatusCode != 200 || !bytes.Equal(body, payloads[index]) {
			t.Fatal("Native public chunk bytes differ")
		}
		if response.Header.Get("Access-Control-Allow-Origin") != "https://pool.pmh.codes" {
			t.Fatal("Native download CORS differs")
		}
	}
	fmt.Println("PASS: original native upload/storage/SQL trigger/collection ordering/public download bytes/CORS; no user authentication fabricated")
}
