# DigitalOcean Deployment Guide

## Prerequisites
- DigitalOcean account (sign up at https://digitalocean.com)
- Credit card or PayPal for billing (~$6/month)

## Step 1: Create a Droplet

1. Go to https://cloud.digitalocean.com/droplets/new
2. Choose an image: **Ubuntu 22.04 (LTS) x64**
3. Choose a plan:
   - **Basic** plan
   - **Regular CPU**
   - **$6/month** (1 GB RAM, 1 vCPU, 25 GB SSD)
   - Or **$12/month** for better performance (2 GB RAM, 1 vCPU)
4. Choose a datacenter region close to you (e.g., San Francisco, New York)
5. Authentication:
   - **SSH Key** (recommended) - Upload your public key
   - Or **Password** (less secure)
6. Hostname: `chatgpt-webrtc`
7. Click **Create Droplet**
8. Wait 55 seconds for the droplet to boot
9. Note your droplet's **public IP address**

## Step 2: Connect to Your Droplet

### Via SSH (if using SSH key):
```bash
ssh root@YOUR_DROPLET_IP
```

### Via Password (if using password):
```bash
ssh root@YOUR_DROPLET_IP
# Enter the password you received via email
```

## Step 3: Deploy the Application

Once connected to your droplet, run these commands:

```bash
# Download the deployment script
curl -O https://raw.githubusercontent.com/wheel-is/chatgpt-login/chore-rm-webrtc-sim-Zajdx/Zajdx/deploy-digitalocean.sh

# Make it executable
chmod +x deploy-digitalocean.sh

# Run the deployment
./deploy-digitalocean.sh
```

**Or manually:**

```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Clone and deploy
git clone https://github.com/wheel-is/chatgpt-login.git
cd chatgpt-login
git checkout chore-rm-webrtc-sim-Zajdx
cd Zajdx
sudo docker-compose up --build -d
```

## Step 4: Access Your Application

Open your browser and go to:
```
http://YOUR_DROPLET_IP:8080
```

You should see the ChatGPT Login WebRTC interface!

## Step 5: Enable HTTPS (Optional but Recommended)

### Get a Domain Name
1. Register a domain (e.g., from Namecheap, Cloudflare)
2. Point an A record to your droplet's IP address
3. Wait for DNS propagation (~5-60 minutes)

### Install SSL Certificate
```bash
# Install Nginx and Certbot
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx

# Create Nginx config
sudo tee /etc/nginx/sites-available/chatgpt-webrtc << 'EOF'
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

# Enable the site
sudo ln -s /etc/nginx/sites-available/chatgpt-webrtc /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx

# Get SSL certificate
sudo certbot --nginx -d your-domain.com

# Auto-renew SSL (runs automatically)
sudo systemctl enable certbot.timer
```

Now access via HTTPS:
```
https://your-domain.com
```

## Useful Commands

### Check Status
```bash
cd /opt/chatgpt-login/Zajdx  # or wherever you cloned
sudo docker-compose ps
sudo docker-compose logs -f
```

### Restart
```bash
sudo docker-compose restart
```

### Update to Latest Code
```bash
cd /opt/chatgpt-login/Zajdx
git pull origin chore-rm-webrtc-sim-Zajdx
sudo docker-compose down
sudo docker-compose up --build -d
```

### Stop
```bash
sudo docker-compose down
```

### View Resource Usage
```bash
docker stats
htop  # if installed: sudo apt install htop
```

## Firewall Configuration (Optional)

For better security:

```bash
# Install UFW
sudo apt install ufw

# Allow SSH, HTTP, HTTPS
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 8080/tcp

# Allow TURN server ports
sudo ufw allow 3478/tcp
sudo ufw allow 3478/udp
sudo ufw allow 5349/tcp

# Enable firewall
sudo ufw enable
```

## Troubleshooting

### Container won't start
```bash
sudo docker-compose logs
```

### Out of memory
Upgrade to a larger droplet or add swap:
```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### WebRTC connection fails
Check that ports 3478 and 5349 are open:
```bash
sudo ufw status
```

## Cost Estimate

- **$6/month** - Basic droplet (1 GB RAM)
- **$12/month** - Better performance (2 GB RAM)
- **~$1-2/month** - Bandwidth (included: 1 TB)

**Total: $6-14/month**

## Support

For issues or questions, check the repository:
https://github.com/wheel-is/chatgpt-login

