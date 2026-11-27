FROM golang:1.23-alpine AS build
WORKDIR /src
COPY go.mod ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/jobnest-crawler ./cmd/crawler

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/jobnest-crawler /jobnest-crawler
EXPOSE 8081
ENTRYPOINT ["/jobnest-crawler"]
