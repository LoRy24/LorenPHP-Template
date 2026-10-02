FROM composer:2 AS dependencies
WORKDIR /app
COPY composer.* ./
COPY src/ src/
RUN composer install --no-interaction --no-dev --ignore-platform-reqs --prefer-dist --optimize-autoloader

FROM dunglas/frankenphp:static-builder-gnu

WORKDIR /go/src/app/dist/app
COPY Caddyfile composer.json ./
COPY public/ public/
COPY src/ src/
COPY --from=dependencies /app/vendor/ vendor/

WORKDIR /go/src/app
RUN --mount=type=secret,id=github_token,env=GITHUB_TOKEN \
    PHP_EXTENSIONS=ctype,iconv,mbstring,opcache,openssl,pdo,pdo_mysql,pdo_pgsql,mongodb,redis \
    EMBED=dist/app/ ./build-static.sh
