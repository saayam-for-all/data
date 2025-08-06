# Overview
This document explains how to connect to the Amazon RDS instance used in this project. It includes details on prerequisites, connection methods, credentials management, and troubleshooting steps.

1. 🔑 Prerequisites
Before you start, ensure you have the following:

AWS Account access (with permission to view RDS instance details)

Database client (e.g., DBeaver, pgAdmin, MySQL Workbench, or CLI tools)

Network access to the RDS instance (ensure security group/Firewall rules are configured)

Database credentials (username and password)

RDS endpoint (hostname, port)

| Parameter     | Description                           | Example                                              |
| ------------- | ------------------------------------- | ---------------------------------------------------- |
| Engine        | Database engine (MySQL/Postgres/etc.) | `PostgreSQL 14`                                      |
| Endpoint      | RDS hostname                          | `mydb-instance.xxxxxxxx.us-east-1.rds.amazonaws.com` |
| Port          | DB port                               | `5432`                                               |
| Username      | Database username                     | `db_user`                                            |
| Password      | Database password                     | `******`                                             |
| Database Name | Target database                       | `project_db`                                         |

3. 🔌 Connection Methods
Option 1: Using a Database Client (GUI)
Open your preferred client (e.g., DBeaver, MySQL Workbench).

Create a new connection.

Enter the following details:

Host: <RDS Endpoint>

Port: <DB Port>

Database Name: <DB Name>

Username: <DB User>

Password: <DB Password>

Test the connection.

Save and connect.

4. 🔒 Credentials Management
Do NOT hardcode passwords in scripts.

Use AWS Secrets Manager or SSM Parameter Store for secure storage.

For local development, you may use .env files (never commit to Git).

| Issue                            | Cause                         | Resolution                                  |
| -------------------------------- | ----------------------------- | ------------------------------------------- |
| `Connection timed out`           | Security group/firewall issue | Allow inbound rules for DB port (e.g. 5432) |
| `Invalid credentials`            | Wrong username/password       | Verify from AWS console or Secrets Manager  |
| `FATAL: database does not exist` | Wrong database name           | Check available databases in RDS instance   |
| SSL errors                       | SSL required for connection   | Enable SSL in client or add SSL params      |

