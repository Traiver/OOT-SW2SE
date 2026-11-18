# syntax=docker/dockerfile:1
#
# Web version of OOT SW2SE as a small container image: static-web-server
# serving the page built by web/build.mjs, and nothing else. Build from the
# repository root:
#
#   docker build -f web/Dockerfile -t oot-sw2se-web .
#   docker run --rm -p 8080:8080 oot-sw2se-web     # then open http://localhost:8080
#
# Stages:
#   build   builds the page (web/dist) with Node.js
#   test    runs the editor and web host tests against it; the image is
#           copied from here, so it is never built from code that fails them
#   site    only the built page, for `--target site --output <folder>`
#   server  static-web-server, for its binary
#   (last)  the image: the server binary, its settings and the page
#
# Node.js stages run on the build machine's own platform ($BUILDPLATFORM) and
# their output doesn't depend on the target, so images for other platforms
# need no emulation and share one cached build.

ARG NODE_IMAGE=node:24.22.2-alpine@sha256:a34ab6d7f6f4813f4d0c5469d74685604b962fbdbf5793a7bc7b4998ecb867c8
ARG SERVER_IMAGE=joseluisq/static-web-server:2.44.1@sha256:94618e3d17802265a21926217e6f9e7832b311b6fbf5933684001739fafed06a

FROM --platform=$BUILDPLATFORM ${NODE_IMAGE} AS build
WORKDIR /src
COPY LICENSE Program.cs editor.html editor.ico ./
COPY web/build.mjs web/browser-host.js web/
RUN node web/build.mjs --out /site

FROM build AS test
COPY tests/editor.test.cjs tests/web-host.test.cjs tests/
RUN node --test tests/editor.test.cjs tests/web-host.test.cjs

FROM scratch AS site
COPY --from=test /site /

FROM ${SERVER_IMAGE} AS server

FROM scratch
COPY --from=server /static-web-server /static-web-server
COPY web/sws.toml /etc/sws.toml
COPY --from=test /site /public
ENV SERVER_CONFIG_FILE=/etc/sws.toml
# Any user works: the server only reads /public, so the image also runs with
# a read-only root filesystem and no capabilities.
USER 65534:65534
EXPOSE 8080
ENTRYPOINT ["/static-web-server"]
