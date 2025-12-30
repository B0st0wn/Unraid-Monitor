ARG BUILD_FROM
FROM $BUILD_FROM

# Install system dependencies
RUN apk add --no-cache bash

# Set working directory
WORKDIR /opt

# Copy requirements and install Python dependencies
COPY app/requirements.txt /opt/app/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /opt/app/requirements.txt

# Copy application code
COPY app/ /opt/app/

# Copy and set up startup script
COPY run.sh /
RUN chmod a+x /run.sh

# Start the application
CMD ["/run.sh"]
