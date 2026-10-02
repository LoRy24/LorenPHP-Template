FROM phpmyadmin:5.2

ADD https://files.phpmyadmin.net/themes/boodark/1.2.0/boodark-1.2.0.zip /tmp/boodark.zip
RUN echo "28bc5fd187727a2800cd6e1ee9f82a59ba28a54301696fa1ef068ecf27d9d9de  /tmp/boodark.zip" | sha256sum -c - \
    && php -r '$zip = new ZipArchive(); if ($zip->open("/tmp/boodark.zip") !== true || !$zip->extractTo("/var/www/html/themes")) { exit(1); }' \
    && rm /tmp/boodark.zip
COPY docker/phpmyadmin.config.php /etc/phpmyadmin/config.user.inc.php
