# Invoice Management System - Deployment Guide

## Server Requirements

- **OS**: Ubuntu 22.04 LTS
- **RAM**: 2GB minimum (4GB recommended)
- **Storage**: 40GB SSD
- **Hetzner**: CX21 or higher

---

## Quick Deployment

### Step 1: Create Hetzner Server

1. Go to [Hetzner Cloud Console](https://console.hetzner.cloud)
2. Create new project or select existing
3. Add Server:
   - Location: Choose closest to your users
   - Image: Ubuntu 22.04
   - Type: CX21 (2 vCPU, 4GB RAM, 40GB SSD)
   - SSH Key: Add your public key
4. Note your server's IP address

### Step 2: Upload Application Files

From your local machine (Windows):
```powershell
# Using SCP (install OpenSSH if needed)
scp -r "C:\Users\Jake\Council test\invoice_management" root@YOUR_SERVER_IP:/tmp/
```

Or use WinSCP/FileZilla to upload the `invoice_management` folder to `/tmp/` on the server.

### Step 3: Run Deployment Script

SSH into your server:
```bash
ssh root@YOUR_SERVER_IP
```

Run the deployment:
```bash
cd /tmp/invoice_management/deploy
chmod +x deploy.sh
./deploy.sh
```

### Step 4: Configure the Application

1. Create your `.env` file:
```bash
cp /opt/invoice_management/.env.example /opt/invoice_management/.env
nano /opt/invoice_management/.env
```

2. Fill in your values:
   - `OPENROUTER_API_KEY` - Get from https://openrouter.ai/keys
   - `EXTERNAL_BACKUP_PATH=/opt/invoice_backups` (already set up)
   - OAuth credentials (optional, for email feature)

3. Update Nginx with your IP/domain:
```bash
nano /etc/nginx/sites-available/invoice_management
# Change YOUR_DOMAIN_OR_IP to your server IP
systemctl restart nginx
```

### Step 5: Start the Application

```bash
systemctl start invoice_management
systemctl status invoice_management
```

### Step 6: Access Your Application

Open in browser: `http://YOUR_SERVER_IP`

---

## Managing the Application

### View Logs
```bash
# Live logs
journalctl -u invoice_management -f

# Last 100 lines
journalctl -u invoice_management -n 100
```

### Restart Application
```bash
systemctl restart invoice_management
```

### Stop Application
```bash
systemctl stop invoice_management
```

### Check Status
```bash
systemctl status invoice_management
```

---

## Backup Management

### Backup Locations
- **Primary**: `/opt/invoice_management/backups/`
- **External**: `/opt/invoice_backups/` (if configured)
- **Receipts**: included inside full backup `.zip` artifacts

### View Backups via SSH
```bash
ls -la /opt/invoice_management/backups/
```

### Download Backup to Local Machine
```bash
# From your local Windows machine:
scp root@YOUR_SERVER_IP:/opt/invoice_management/backups/FILENAME.db ./
```

### Manual Full Backup (DB + Receipts) via Command Line
```bash
cd /opt/invoice_management
source venv/bin/activate
python -c "from services.backup_service import create_full_backup; create_full_backup('manual-ssh')"
```

### Restore from Backup
Use the web interface at `/settings` or:
```bash
cd /opt/invoice_management
source venv/bin/activate
python -c "from services.backup_service import restore_full_backup; restore_full_backup('FILENAME.zip')"
systemctl restart invoice_management
```

### Monthly Restore Drill (No Production Changes)
```bash
cd /opt/invoice_management
source venv/bin/activate
python tools/run_restore_drill.py
```

### Daily Integrity Check (Missing/Orphan/Checksum)
```bash
cd /opt/invoice_management
source venv/bin/activate
python tools/run_receipt_integrity_check.py
```

To schedule nightly (2:30 AM) as `invoiceapp`:
```bash
crontab -e -u invoiceapp
# Add:
30 2 * * * cd /opt/invoice_management && /opt/invoice_management/venv/bin/python tools/run_receipt_integrity_check.py >> /opt/invoice_management/backups/receipt_integrity_cron.log 2>&1
```

---

## SSL/HTTPS Setup (Recommended)

After basic setup is working:

```bash
# Install Certbot
apt install certbot python3-certbot-nginx

# Get SSL certificate (replace with your domain)
certbot --nginx -d your-domain.com

# Auto-renewal is set up automatically
# Test with: certbot renew --dry-run
```

---

## Updating the Application

1. Upload new files:
```bash
scp -r "C:\path\to\invoice_management" root@YOUR_SERVER_IP:/tmp/
```

2. On server:
```bash
systemctl stop invoice_management
cp -r /tmp/invoice_management/* /opt/invoice_management/
cd /opt/invoice_management
source venv/bin/activate
pip install -r requirements.txt
chown -R invoiceapp:invoiceapp /opt/invoice_management
systemctl start invoice_management
```

---

## Troubleshooting

### Application won't start
```bash
# Check logs
journalctl -u invoice_management -n 50

# Common issues:
# - Missing .env file
# - Python package not installed
# - Permission issues
```

### Permission denied errors
```bash
chown -R invoiceapp:invoiceapp /opt/invoice_management
chmod -R 750 /opt/invoice_management
```

### Database locked
```bash
systemctl restart invoice_management
```

### Nginx 502 Bad Gateway
```bash
# Check if app is running
systemctl status invoice_management

# Check Nginx config
nginx -t

# Restart both
systemctl restart invoice_management
systemctl restart nginx
```

---

## Security Checklist

- [ ] SSH key authentication only (disable password)
- [ ] Firewall enabled (ufw)
- [ ] SSL/HTTPS configured
- [ ] .env file has restricted permissions (640)
- [ ] Regular backups verified
- [ ] External backup location configured

---

## Useful Commands Reference

```bash
# Service management
systemctl start invoice_management
systemctl stop invoice_management
systemctl restart invoice_management
systemctl status invoice_management

# Logs
journalctl -u invoice_management -f
journalctl -u invoice_management --since "1 hour ago"

# Nginx
systemctl restart nginx
nginx -t
tail -f /var/log/nginx/error.log

# Firewall
ufw status
ufw allow 80
ufw allow 443

# Disk space
df -h
du -sh /opt/invoice_management/backups/
```
