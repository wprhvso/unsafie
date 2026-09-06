set dotenv-load := true
set dotenv-filename := "client.env"
set shell := ["bash", "-uc"]

ver := env_var_or_default("VERSION", "dev")
relver := trim_start_match(ver, "v")

updateflags := if relver == "dev" { "" } else { \
    " -X main.buildUpdateURL=" + env_var("UPDATE_BASEURL") + \
    " -X main.buildUpdateToken=" + env_var("UPDATE_TOKEN") + \
    " -X main.buildUpdateKey=" + env_var("RELEASE_PUBKEY") }

ldflags := "-s -w -buildid=" + \
    " -X main.buildEdges=" + env_var("EDGE_HOSTS") + \
    " -X main.buildPort=" + env_var("EDGE_PORT") + \
    " -X main.buildBearer=" + env_var("CLIENT_TOKEN") + \
    " -X main.buildVersion=" + relver + \
    updateflags

default:
    just --list

check-tunnel: vet test zig-test

vet:
    go -C go vet ./...

test:
    go -C go test ./...

fmt:
    go -C go fmt ./...
    zig fmt zig/src zig/build.zig

lint:
    cd go && golangci-lint run ./...

zig-build:
    zig build --build-file zig/build.zig -Doptimize=ReleaseFast

zig-test:
    zig build --build-file zig/build.zig test

# The exit, in the foreground, with a resolver you can watch.
edge port="8091" region="local" country="XX":
    zig build --build-file zig/build.zig run -- \
        --listen 127.0.0.1:{{port}} --region {{region}} --country {{country}} --verbose

# One real connection through a locally running exit.
uspcheck base="http://127.0.0.1:8091" target="example.com:80":
    go -C go run ./cmd/uspcheck -base {{base}} -target {{target}}

# What the client claims to be.
fingerprint:
    go -C go run ./cmd/uspcheck -h 2>/dev/null || true
    curl -fsS http://127.0.0.1:9977/fingerprint || true

client:
    #!/usr/bin/env bash
    set -euo pipefail
    CGO_ENABLED=0 go build -C go -trimpath -ldflags="{{ldflags}}" -o ../dist/unsafie .

kotlin-test:
    gradle -p android test
