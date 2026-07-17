# About Project

## Problems
This project is for solving 5 problem of RM (Risk Management)
1. RM Capacity is Overloading
    - 200-500+ clients per RM
    - Administrative tasks take too much time
    - Data in multiple systems
    - Manual reporting & preparation
2. Don’t know which clients to contact (Priority & Urgency)
    - 200-500+ clients per RM
    - Hundreds of events every day
    - NO intelligent prioritization
    - RMs contract based on guesswork or whoever calls first
3. Don’t Have Expertise in All Products
    - Too many products & solutions
    - Complexity increases every year
    - Impossible to master everything
    - Rely on what they know or sold before
4. Inactive or At-Risk Client Relationships
    - Many clients inactive for 6-24+ months
    - No visibility on who to re-engage
    - Idle cash or matured investments
    - No system to signal early
5. KYC Registration, Renewal, and Compliance 
    - KYC must be renewed periodically
    - RMs manually track expiry dates
    - Time-consuming follow ups
    - High risk of missing or being late

## Solutions
We implement 4 solutions to solve these 4 problem
1. Attention and Channel Module
    - This module will tell "who shoule be attention" and what channel they will be in Care Lane or Growth Lane:
        - Care Lane: KYC/profile review, suitability conflict, critical goal at risk, liquidity shortfall, severe concentration, vulnerable‐client need and unresolved service issue.
        - Growth Lane: confirmed or strongly evidenced planning need ex. retirement, protection, financing, excess liquidity, tax event or investable cash after liquidity reserve.
    Business value can not override mandatory care, suitability or client‐benefit gate.
2. Product Recommendation Module
    - This module will recieve input as client goals, client need or etc. then output is a list of product which match the problem.
3. Dashboard Active Clients
    - This dashboard will show the active status of clients ex. last deposit, last withdraw, last trade etc.
4. Dashboard KYC
    - This dashboard will show KYC status of each client

## Webpage
- Home page (Module 1): Showing list of customer must be attention from Attention and Channel Module in everydays
- Product Recommendation Page (Module 2): This page can choose client and client goals for find products which match input
- Active Status Clients Page (Module 3): Showing dashboard which can tell active status of each client
- KYC Page (Module 4): Showing dashboard which tell about KYC status of each client

## System Design
Data Source -> Data Gate -> Modules -> Frontend
- Data Source
    - SETSMART api
    - Client 360, Goal Ledger (Mock up)
    - KYC/CRM, permission, mandate
- Data Gate
- Modules
    - Attention and Channel Module
    - Product Recommendation Module
    - KYC module
- Frontend web app

## Frontend Style
- use style in GTYLE_GUILDE.md

## Project Structure
- .venv
- src
    - data_gate (python)
    - modules (python)
    - frontend (JS)
- .env
- .gitignore
- package.json
- README.md