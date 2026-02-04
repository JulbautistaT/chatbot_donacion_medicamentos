FROM python:3.10.17-bullseye

ARG USER_ID=1000
ARG GROUP_ID=1000

ENV LC_ALL=es_ES.UTF-8
ENV LANG=es_ES.UTF-8
ENV LANGUAGE=es_ES.UTF-8


# install jq
RUN apt-get update -y && apt-get install -y \
    curl \
    firefox-esr \
    jq \
    libasound2 \
    libdbus-glib-1-2 \
    libfontconfig1 \
    libgtk-3-0 \
    libjpeg-dev \
    libnspr4 \
    libnss3 \
    libpangocairo-1.0-0 \
    libpangoft2-1.0-0 \
    libpng-dev \
    libtiff-dev \
    libwebp-dev \
    libx11-xcb1 \
    libxcb-shm0 \
    libxcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxinerama1 \
    libxkbcommon0 \
    libxrandr2 \
    libxrender1 \
    libxt6 \
    poppler-utils \
    tesseract-ocr \
    unzip \
    wget \
    xvfb \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*



# Install GeckoDriver
RUN wget -q https://github.com/mozilla/geckodriver/releases/download/v0.36.0/geckodriver-v0.36.0-linux64.tar.gz \
    && tar -xvzf geckodriver-v0.36.0-linux64.tar.gz \
    && mv geckodriver /usr/local/bin/ \
    && chmod +x /usr/local/bin/geckodriver \
    && rm geckodriver-v0.36.0-linux64.tar.gz




# Create non-privileged user
RUN addgroup --gid $GROUP_ID app
RUN adduser --disabled-password --gecos '' --uid $USER_ID --gid $GROUP_ID app
USER app


ENV HOME=/home/app
WORKDIR $HOME
ENV PATH=$HOME/.local/bin:$PATH
ENV DISPLAY=:99
COPY . .

ADD requirements.txt $HOME/requirements.txt

RUN pip install --no-cache-dir --upgrade pip
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt



CMD ["sh", "-c", "Xvfb :99 -screen 0 1920x1080x24"]