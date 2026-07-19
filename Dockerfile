FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install Python + system dependencies
RUN apt-get update && apt-get install -y \
    python3.11 \
    python3.11-pip \
    python3.11-venv \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Make python default
RUN ln -sf /usr/bin/python3.11 /usr/bin/python
RUN ln -sf /usr/bin/pip3 /usr/bin/pip

COPY requirements.txt .

RUN pip install --upgrade pip

RUN pip install --no-cache-dir -r requirements.txt


# Install playwright browsers
RUN playwright install --with-deps chromium


COPY . .

EXPOSE 10000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "10000"]