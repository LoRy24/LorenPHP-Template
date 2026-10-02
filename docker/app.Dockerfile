FROM dunglas/frankenphp:1-php8.4

RUN install-php-extensions pdo_mysql pdo_pgsql mongodb redis
COPY --from=composer:2 /usr/bin/composer /usr/bin/composer
WORKDIR /app
COPY docker/Caddyfile /etc/frankenphp/Caddyfile
COPY composer.* ./
COPY public/ public/
COPY src/ src/
RUN composer install --no-interaction --prefer-dist --optimize-autoloader
