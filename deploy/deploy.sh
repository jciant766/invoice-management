#!/bin/bash
# Invoice Management System - Ubuntu 22.04 Deployment Script
# Run as root: sudo bash deploy.sh

set -e  # Exit on any error

echo "=========================================="
echo "Invoice Management System - Deployment"
echo "=========================================="

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: Please run as root (sudo bash deploy.sh)"
    exit 1
fi

# Variables
APP_DIR="/opt/invoice_management"
APP_USER="invoiceapp"
BACKUP_DIR="/opt/invoice_backups"

echo ""
echo "[1/8] Updating system packages..."
apt update && apt upgrade -y

echo ""
echo "[2/8] Installing required packages..."
apt install -y python3.11 python3.11-venv python3-pip nginx ufw git

echo ""
echo "[3/8] Creating application user..."
if ! id "$APP_USER" &>/dev/null; then
    useradd --system --shell /bin/false --home-dir $APP_DIR $APP_USER
    echo "User '$APP_USER' created"
else
    echo "User '$APP_USER' already exists"
fi

echo ""
echo "[4/8] Setting up application directory..."
mkdir -p $APP_DIR
mkdir -p $BACKUP_DIR

# Copy application files (assuming you've uploaded them to /tmp/invoice_management)
if [ -d "/tmp/invoice_management" ]; then
    cp -r /tmp/invoice_management/* $APP_DIR/
    echo "Application files copied from /tmp/invoice_management"
else
    echo "WARNING: Upload your application files to /tmp/invoice_management first"
    echo "You can use: scp -r ./invoice_management root@YOUR_SERVER:/tmp/"
fi

echo ""
echo "[5/8] Setting up Python virtual environment..."
cd $APP_DIR
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

echo ""
echo "[6/8] Setting up systemd service..."
cp $APP_DIR/deploy/invoice_management.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable invoice_management

echo ""
echo "[7/8] Setting up Nginx..."
cp $APP_DIR/deploy/nginx.conf /etc/nginx/sites-available/invoice_management
ln -sf /etc/nginx/sites-available/invoice_management /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default  # Remove default site
nginx -t  # Test configuration
systemctl restart nginx
systemctl enable nginx

echo ""
echo "[8/8] Setting up firewall..."
ufw allow ssh
ufw allow 'Nginx Full'
ufw --force enable

echo ""
echo "Setting file permissions..."
chown -R $APP_USER:$APP_USER $APP_DIR
chown -R $APP_USER:$APP_USER $BACKUP_DIR
chmod -R 750 $APP_DIR
chmod 640 $APP_DIR/.env 2>/dev/null || echo "Note: Create .env file from .env.example"

echo ""
echo "=========================================="
echo "DEPLOYMENT COMPLETE!"
echo "=========================================="
echo ""
echo "NEXT STEPS:"
echo "1. Create .env file:"
echo "   cp $APP_DIR/.env.example $APP_DIR/.env"
echo "   nano $APP_DIR/.env"
echo ""
echo "2. Edit Nginx config with your domain/IP:"
echo "   nano /etc/nginx/sites-available/invoice_management"
echo "   systemctl restart nginx"
echo ""
echo "3. Start the application:"
echo "   systemctl start invoice_management"
echo ""
echo "4. Check status:"
echo "   systemctl status invoice_management"
echo ""
echo "5. View logs:"
echo "   journalctl -u invoice_management -f"
echo ""
echo "6. (Optional) Set up SSL with Let's Encrypt:"
echo "   apt install certbot python3-certbot-nginx"
echo "   certbot --nginx -d your-domain.com"
echo ""
echo "External backup location: $BACKUP_DIR"
echo "Add to .env: EXTERNAL_BACKUP_PATH=$BACKUP_DIR"
echo ""
