# Financehub
Personal finance application

---

## Deployment — Hostinger

### Prerequisites
- PHP 8.2+ enabled in hPanel → PHP Configuration
- MySQL database created in hPanel → Databases → MySQL Databases
- SSH access enabled (recommended)

### 1. Point Document Root to `public/`
In hPanel → Hosting → Manage → Configuration, set the document root to `public_html/financehub/public`.
Or symlink if the root is fixed:
```bash
ln -s ~/financehub/public ~/public_html
```

### 2. Deploy via SSH + Git
```bash
git clone https://github.com/selweshype/financehub.git ~/financehub
cd ~/financehub
composer install --optimize-autoloader --no-dev
```

### 3. Configure Environment
```bash
cp .env.example .env
# Edit .env with your Hostinger MySQL credentials
nano .env
php artisan key:generate
```

### 4. Run Migrations
```bash
php artisan migrate --force
```

### 5. Set Permissions
```bash
chmod -R 775 storage bootstrap/cache
```

### 6. Optimize for Production
```bash
php artisan config:cache
php artisan route:cache
php artisan view:cache
php artisan storage:link
```

### Rollback
```bash
php artisan down
git pull origin main
composer install --no-dev --optimize-autoloader
php artisan migrate --force
php artisan optimize
php artisan up
```

### Notes
- **Shared hosting**: `QUEUE_CONNECTION=sync`, `CACHE_STORE=file`, `SESSION_DRIVER=file`
- **VPS**: Switch to `redis` for cache/session and `database` for queue (add Supervisor worker)
- **Apache `.htaccess`** is included in `public/` and handles URL rewriting — no server config change needed on Hostinger shared hosting
