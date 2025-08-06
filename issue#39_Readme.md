# Overview
This document explains how to connect to the Amazon RDS instance. It includes details on prerequisites, how to make connection, credentials management, and troubleshooting steps.

1. 🔑 Prerequisites
Before you start, ensure you have the following:

- AWS Account access
- Any open source Database client (e.g., DBeaver, pgAdmin, MySQL Workbench)
- Network access to the RDS instance (ensure security group/Firewall rules are configured)
- Database credentials (username and password)
- RDS endpoint (hostname, port of the instance)

| Parameter     | Description                           | Example                                              |
| ------------- | ------------------------------------- | ---------------------------------------------------- |
| Engine        | Database engine (MySQL/Postgres/etc.) | `PostgreSQL 14`                                      |
| Endpoint      | RDS hostname                          | `mydb-instance.xxxxxxxx.us-east-1.rds.amazonaws.com` |
| Port          | DB port                               | `5432`                                               |
| Username      | Database username                     | `db_user`                                            |
| Password      | Database password                     | `******`                                             |
| Database Name | Target database                       | `project_db`                                         |

3. 🔌 How to make connection
## Using a Database Client (GUI)

- Open your preferred client (e.g., DBeaver, MySQL Workbench).
- Create a new connection.
- Enter the required details to make connection:
-- Host: <RDS Endpoint>
-- Port: <DB Port>
-- Database Name: <DB Name>
-- Username: <DB User>
-- Password: <DB Password>
-- Test the connection.
-- Save and connect.

4. 🔒 Credentials Management
- Do NOT hardcode passwords in scripts.
- Use AWS Secrets Manager.
- For local development and testing, you may use .env files

5. 📫 Possible issues and resolution
   
| Issue                            | Cause                         | Resolution                                  |
| -------------------------------- | ----------------------------- | ------------------------------------------- |
| Connection timed out             | Security group/firewall issue | Allow inbound rules for DB specific port    |
| Invalid credentials              | Wrong username/password       | Verify from AWS console or Secrets Manager  |
| FATAL: database does not exist   | Wrong database name           | Check available databases in RDS instance   |
| SSL errors                       | SSL required for connection   | import the SSL credentials in connections   |

