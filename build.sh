#!/bin/bash

# Build script cho Render
set -e

echo "🔧 Bắt đầu build script..."

# Cập nhật hệ thống và dọn dẹp thư mục tạm
apt-get update
rm -rf /var/lib/apt/lists/* || true
apt-get install -y wget gnupg unzip curl

# Cài đặt Google Chrome
wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add -
echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list
apt-get update
rm -rf /var/lib/apt/lists/* || true
apt-get install -y google-chrome-stable

# Cài đặt Python packages
pip install --upgrade pip
pip install -r requirements.txt

echo "✅ Build hoàn thành!"