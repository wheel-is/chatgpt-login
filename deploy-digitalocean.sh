#!/bin/bash
set -e

echo "🚀 ChatGPT Login WebRTC - DigitalOcean Deployment Script"
echo "========================================================="
echo ""

# Check if running on DigitalOcean droplet
if [ ! -f /etc/os-release ]; then
    echo "❌ This script should be run on a DigitalOcean Ubuntu droplet"
    exit 1
fi

echo "📦 Installing Docker and Docker Compose..."
sudo apt-get update
sudo apt-get install -y apt-transport-https ca-certificates curl software-properties-common

# Install Docker
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -
sudo add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Add current user to docker group
sudo usermod -aG docker $USER

echo "✅ Docker installed successfully!"
echo ""

echo "🔧 Cloning repository..."
if [ -d "/opt/chatgpt-login" ]; then
    echo "Repository already exists, pulling latest..."
    cd /opt/chatgpt-login/Zajdx
    git pull origin chore-rm-webrtc-sim-Zajdx
else
    sudo git clone https://github.com/wheel-is/chatgpt-login.git /opt/chatgpt-login
    cd /opt/chatgpt-login
    git checkout chore-rm-webrtc-sim-Zajdx
    cd Zajdx
fi

echo "✅ Repository ready!"
echo ""

echo "🐳 Building and starting Docker containers..."
sudo docker-compose down 2>/dev/null || true
sudo docker-compose up --build -d

echo ""
echo "✅ Deployment complete!"
echo ""
echo "📍 Your WebRTC server is now running!"
echo ""
echo "🌐 Access it at: http://$(curl -s ifconfig.me):8080"
echo ""
echo "📊 Check status with: sudo docker-compose logs -f"
echo "🔄 Restart with: sudo docker-compose restart"
echo "🛑 Stop with: sudo docker-compose down"
echo ""
echo "🔐 To enable HTTPS (recommended):"
echo "   1. Point a domain to this droplet's IP"
echo "   2. Run: sudo apt install nginx certbot python3-certbot-nginx"
echo "   3. Run: sudo certbot --nginx -d your-domain.com"
echo ""

