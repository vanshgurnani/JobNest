package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/vanshgurnani/jobnest/crawler-go/internal/crawler"
	"github.com/vanshgurnani/jobnest/crawler-go/internal/httpapi"
	"github.com/vanshgurnani/jobnest/crawler-go/internal/storage"
)

func main() {
	if os.Getenv("CRAWLER_API_TOKEN") == "" { log.Fatal("CRAWLER_API_TOKEN is required") }
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	store, err := storage.New(ctx, os.Getenv("MONGO_URI"), os.Getenv("MONGO_DB_NAME"))
	if err != nil { log.Fatalf("mongo initialization: %v", err) }
	defer store.Close(context.Background())

	engine := crawler.New(store, crawler.ConfigFromEnv())
	handler := httpapi.New(engine, os.Getenv("CRAWLER_API_TOKEN"))
	server := &http.Server{Addr: env("CRAWLER_ADDR", ":8081"), Handler: handler, ReadHeaderTimeout: 5*time.Second}
	go func(){ log.Printf("Go crawler listening on %s", server.Addr); if err:=server.ListenAndServe(); err!=nil && err!=http.ErrServerClosed { log.Fatalf("http server: %v",err) } }()
	<-ctx.Done()
	shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second); defer cancel()
	_ = server.Shutdown(shutdown)
}

func env(key, fallback string) string { if v:=os.Getenv(key); v!="" { return v }; return fallback }
