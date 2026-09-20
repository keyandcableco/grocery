# Adding `groceries` to flask-stack

Plain-slim app (SQLite, no LaTeX) — same family as GTD_App / gear-manager.
gunicorn is in requirements; container listens on 8000 internally.

## 1. docker-compose.yml — add this service block

```yaml
  groceries:
    build: ./grocery
    restart: unless-stopped
    volumes:
      - ./grocery/data:/app/instance
    environment:
      - GROCERY_SECRET=${GROCERY_SECRET}
      - GROCERY_DB_URI=sqlite:////app/instance/grocery.db
      - SMTP_HOST=${SMTP_HOST}
      - SMTP_USER=${SMTP_USER}
      - SMTP_PASS=${SMTP_PASS}
      - SMTP_FROM=${SMTP_FROM}
      - GROCERY_RECIPIENTS=${GROCERY_RECIPIENTS}
```

No `ports:` — nginx handles external access. Four slashes in the DB URI =
absolute path /app/instance/grocery.db. The data dir bind-mount keeps SQLite
across rebuilds.

## 2. nginx/default.conf — add two server blocks

Subdomain (port 80, desktop):

```nginx
server {
    listen 80;
    server_name groceries.localhost;
    resolver 127.0.0.11;
    location / {
        set $u http://groceries:8000;
        proxy_pass $u;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

Per-port (8006, phone/Tailscale):

```nginx
server {
    listen 8006;
    server_name _;
    resolver 127.0.0.11;
    location / {
        set $u http://groceries:8000;
        proxy_pass $u;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

Copy the proxy_set_header lines from an existing block if yours differ.

## 3. nginx service — add port mapping + depends_on

```yaml
    ports:
      - "8006:8006"      # add alongside existing 8001-8005
    depends_on:
      - groceries        # add to the list
```

## 4. .env — add

```
GROCERY_SECRET=<random-string>
SMTP_HOST=smtp.gmail.com
SMTP_USER=greg@keyandcable.com
SMTP_PASS=<app-password>
SMTP_FROM=greg@keyandcable.com
GROCERY_RECIPIENTS=3523251222@vtext.com
```

## 5. Build & start

```bash
docker compose up -d --build groceries
docker compose restart nginx
```

Desktop: http://groceries.localhost   Phone: http://pugetbl:8006

## 6. One-time Sheet import (after container is up)

```bash
# copy your CSV into ./grocery/ first, then:
docker compose exec groceries python import_sheet.py /app/your_export.csv
```
