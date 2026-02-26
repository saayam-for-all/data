# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Set environment variables
#ENV DATABASE_URL="postgresql://postgres:password@localhost:5432/Saayam"
ENV FLASK_APP=app.py 

# Make port 5000 available to the world outside this container
EXPOSE 5000

# Run the application
CMD ["flask", "run", "--host=0.0.0.0"]

