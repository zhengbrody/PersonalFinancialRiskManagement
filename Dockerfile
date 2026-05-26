FROM python:3.10-slim

WORKDIR /app

# System deps:
#   gcc                — needed for a couple of native wheels at pip install
#   fonts-noto-cjk     — Chinese / Japanese / Korean glyphs. The equity
#                        research PDF builder (libs/analysis/equity_pdf.py)
#                        auto-detects this via _resolve_cjk_font() and
#                        switches the PDF into Unicode mode so CJK risks /
#                        thesis text render correctly. Without it the PDF
#                        sanitiser maps CJK to '?'. The package lands at
#                        /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc
#                        on Debian, which is in our search path.
RUN apt-get update && apt-get install -y \
    gcc \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY . .

# 暴露端口
EXPOSE 8501

# 默认启动Streamlit
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
