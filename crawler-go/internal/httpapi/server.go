package httpapi

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"net/http"
	"strings"
	"time"

	"github.com/vanshgurnani/jobnest/crawler-go/internal/crawler"
)

type Server struct { engine *crawler.Engine; token string }
func New(e *crawler.Engine,token string)http.Handler {
	s:=&Server{engine:e,token:token};mux:=http.NewServeMux()
	mux.HandleFunc("GET /health",func(w http.ResponseWriter,r *http.Request){write(w,200,map[string]any{"status":"ok","service":"jobnest-go-crawler"})})
	mux.HandleFunc("POST /crawl",s.crawl)
	return securityHeaders(mux)
}
func(s *Server)crawl(w http.ResponseWriter,r *http.Request) {
	if s.token=="" { write(w,503,map[string]string{"error":"crawler API token is not configured"}); return }
	auth:=strings.TrimSpace(strings.TrimPrefix(r.Header.Get("Authorization"),"Bearer "))
	if subtle.ConstantTimeCompare([]byte(auth),[]byte(s.token))!=1 { write(w,401,map[string]string{"error":"unauthorized"}); return }
	r.Body=http.MaxBytesReader(w,r.Body,32<<10)
	var in crawler.Request;dec:=json.NewDecoder(r.Body);dec.DisallowUnknownFields()
	if err:=dec.Decode(&in);err!=nil{write(w,400,map[string]string{"error":"invalid request: "+err.Error()});return}
	ctx,cancel:=contextWithTimeout(r);defer cancel()
	result,err:=s.engine.Crawl(ctx,in);if err!=nil{write(w,422,map[string]string{"error":err.Error()});return}
	write(w,200,result)
}
func write(w http.ResponseWriter,status int,v any){w.Header().Set("Content-Type","application/json");w.WriteHeader(status);_ = json.NewEncoder(w).Encode(v)}
func securityHeaders(next http.Handler)http.Handler{return http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){w.Header().Set("X-Content-Type-Options","nosniff");w.Header().Set("Cache-Control","no-store");next.ServeHTTP(w,r)})}
func contextWithTimeout(r *http.Request)(context.Context,context.CancelFunc){return context.WithTimeout(r.Context(),3*time.Minute)}
