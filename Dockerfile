ARG BUILD_FROM
FROM $BUILD_FROM

# Install system dependencies
RUN apk add --no-cache bash

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY app/requirements.txt .
RUN pip install --no-cache-dir --upgrade -r requirements.txt

# Copy application code
COPY app/ .

# Copy and set up startup script
COPY run.sh /
RUN chmod a+x /run.sh

# Start the application
CMD ["/run.sh"]
