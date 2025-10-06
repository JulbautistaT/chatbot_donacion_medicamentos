FROM python:3.10.17-bullseye

ARG USER_ID=1000
ARG GROUP_ID=1000

ENV LC_ALL=es_ES.UTF-8
ENV LANG=es_ES.UTF-8
ENV LANGUAGE=es_ES.UTF-8


# install jq
RUN apt-get update -y && apt-get install -y jq \
    firefox-esr \
    wget \
    curl \
    unzip \
    libgtk-3-0 \
    libdbus-glib-1-2 \
    libxt6 \
    libxrender1 \
    libx11-xcb1 \
    libxcb-shm0 \
    libxcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libasound2 \
    libpangocairo-1.0-0 \
    libpangoft2-1.0-0 \
    libfontconfig1 \
    libxinerama1 \
    libxkbcommon0 \
    libnss3 \
    libnspr4 \
    xvfb \
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
RUN pip install --no-cache-dir -r requirements.txt

CMD ["sh", "-c", "Xvfb :99 -screen 0 1920x1080x24"]