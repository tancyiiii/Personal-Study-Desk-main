#!/bin/bash

# Multi-Agent Study Assistant Setup Script

echo "üöÄ Setting up Multi-Agent Study Assistant..."
echo ""

# Check Python version
echo "üìã Checking Python version..."
python_version=$(python3 --version 2>&1 | awk '{print $2}')
required_version="3.10"

if [ "$(printf '%s\n' "$required_version" "$python_version" | sort -V | head -n1)" != "$required_version" ]; then 
    echo "‚ù?Error: Python 3.10 or higher is required. You have Python $python_version"
    exit 1
fi
echo "‚ú?Python $python_version detected"
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "üìù Creating .env file from template..."
    cp .env.example .env
    echo "‚ú?.env file created"
    echo "‚ö†Ô∏è  IMPORTANT: Edit .env and add your API keys!"
    echo ""
else
    echo "‚ú?.env file already exists"
    echo ""
fi

# Install dependencies
echo "üì¶ Installing dependencies..."
echo "Choose installation method:"
echo "1) uv (recommended - faster)"
echo "2) pip (traditional)"
read -p "Enter choice (1 or 2): " choice

if [ "$choice" = "1" ]; then
    # Check if uv is installed
    if ! command -v uv &> /dev/null; then
        echo "Installing uv..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.cargo/bin:$PATH"
    fi
    echo "Installing with uv..."
    uv sync
elif [ "$choice" = "2" ]; then
    echo "Installing with pip..."
    pip install -r requirements.txt
else
    echo "‚ù?Invalid choice"
    exit 1
fi

echo ""
echo "‚ú?Installation complete!"
echo ""
echo "üéØ Next steps:"
echo "1. Edit .env file and add your API key(s)"
echo "   - Get Groq API key (free): https://console.groq.com"
echo "   - Or OpenAI API key (paid): https://platform.openai.com"
echo ""
echo "2. Run the application:"
echo "   python main_gui.py"
echo ""
echo "3. Open your browser at: (native desktop window)"
echo ""
echo "üìö Happy learning!"
