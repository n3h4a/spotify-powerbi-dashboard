# 🎵 Spotify Music Analytics Dashboard

<p align="center">
  <strong>An interactive Business Intelligence dashboard built with Microsoft Power BI to analyze Spotify music data using Power Query and DAX.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Power%20BI-F2C811?style=for-the-badge&logo=powerbi&logoColor=black"/>
  <img src="https://img.shields.io/badge/DAX-Data%20Analysis-blue?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/Power%20Query-ETL-success?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/Status-Completed-brightgreen?style=for-the-badge"/>
</p>

---

# 📌 Project Overview

The **Spotify Music Analytics Dashboard** is an end-to-end Business Intelligence project developed in **Microsoft Power BI** to transform raw Spotify music data into meaningful, interactive insights.

The dashboard enables users to explore trends in music popularity, artist performance, album releases, and song characteristics through dynamic visualizations and interactive filtering. The project demonstrates the complete analytics workflow, from data cleaning and transformation to data modeling, DAX calculations, and dashboard design.

Whether identifying top-performing artists, tracking release trends over time, or analyzing song popularity, the dashboard provides an intuitive interface for exploring Spotify data.

---

# 🎯 Objectives

- Transform raw Spotify data into actionable insights.
- Analyze artist and song performance.
- Visualize music popularity trends.
- Monitor album and release statistics.
- Build an interactive dashboard for data exploration.
- Demonstrate Business Intelligence and data visualization skills.

---

# 🚀 Features

- 📊 Interactive Dashboard
- 🎛 Dynamic Filters & Slicers
- 📈 KPI Cards
- 🎤 Artist Performance Analysis
- 🎵 Song-Level Insights
- 📅 Release Trend Analysis
- 💿 Album Type Analysis
- 📉 Popularity Distribution
- ⚡ Fast Navigation Between Pages
- 🎨 Clean & Modern Dashboard Design

---

# 📄 Dashboard Pages

## 🏠 Home

The landing page provides seamless navigation across all dashboard sections, creating an intuitive user experience.

**Highlights**

- Dashboard Navigation
- Interactive Buttons
- Clean Landing Interface

> **Screenshot**

```md
![Home Dashboard](screenshots/home.png)

---

## 📈 Overview

The Overview page provides a comprehensive summary of the Spotify dataset using KPI cards and interactive visualizations.

### Key Insights

- Total Songs
- Total Artists
- Average Popularity
- Average Duration
- Album Type Distribution
- Release Trends
- Popularity Distribution

> **Screenshot**

```md
![Home Dashboard](overview/home.png)

---

## 🎤 Artist Analysis

Explore artist performance through detailed visualizations and comparisons.

### Key Insights

- Top Performing Artists
- Artist Popularity
- Songs by Artist
- Album Contributions
- Interactive Comparison

> **Screenshot**

```md
![Home Dashboard](artist/home.png)

---

## 🎧 Song Analysis

Analyze individual songs using multiple interactive visuals.

### Key Insights

- Song Popularity
- Duration Analysis
- Explicit vs Non-Explicit Songs
- Album Information
- Song Rankings

> **Screenshot**

```md
![Home Dashboard](screenshots/songs.png)

---

# 💼 Business Questions Answered

This dashboard helps answer questions such as:

- Which artists have the highest popularity?
- Which songs consistently rank at the top?
- How has music evolved over time?
- Which album types dominate the dataset?
- What is the average popularity of songs?
- How are songs distributed across release years?
- How many songs contain explicit content?
- Which artists contribute the most songs?

---

# 🛠 Data Preparation

Data preprocessing was performed using **Power Query**.

The workflow included:

- Cleaning raw data
- Handling missing values
- Correcting data types
- Formatting date columns
- Creating calculated fields
- Feature engineering for analysis

---

# 📐 DAX Measures

Several DAX measures were created to support dynamic reporting and KPI calculations.

Examples include:

- Total Songs
- Total Artists
- Average Popularity
- Maximum Popularity
- Minimum Popularity
- Average Song Duration
- Distinct Artists
- Custom KPI Measures

---

# 📊 Dataset

The project uses a Spotify dataset containing information such as:

| Attribute |
|-----------|
| Song |
| Artist |
| Popularity |
| Duration |
| Album Type |
| Total Tracks |
| Release Date |
| Explicit |
| Album Cover URL |

---

# 🛠 Tools & Technologies

| Technology | Purpose |
|------------|---------|
| Microsoft Power BI | Dashboard Development |
| Power Query | Data Cleaning & Transformation |
| DAX | Measures & Calculations |
| CSV | Dataset |

---

# 📂 Repository Structure

```
spotify-powerbi-dashboard/
│
├── dashboard/
│   └── Spotify_Music_Analytics.pbix
│
├── dataset/
│   └── spotify_dataset.csv
│
├── screenshots/
│   ├── home.png
│   ├── overview.png
│   ├── artist-analysis.png
│   └── song-analysis.png
│
├── README.md
├── LICENSE
└── .gitignore
```

---

# ▶️ Getting Started

### Clone the repository

```bash
git clone https://github.com/yourusername/spotify-powerbi-dashboard.git
```

### Run the project

1. Install **Microsoft Power BI Desktop**.
2. Open `Spotify_Music_Analytics.pbix`.
3. Refresh the dataset if required.
4. Explore the dashboard using filters, slicers, and interactive visuals.

---

# 🔮 Future Improvements

- Spotify API Integration
- Real-Time Dashboard
- Genre-Based Analytics
- Playlist Analytics
- Listening Behaviour Analysis
- Predictive Analytics
- Mobile Dashboard Optimization

---

# 👩‍💻 Author

**Neha Karamchandani**

B.Tech in Information Technology

Passionate about **Data Analytics**, **Business Intelligence**, **SQL**, **Power BI**, and **Data Visualization**.

---

## ⭐ Support

If you found this project useful or interesting, consider giving it a **Star** ⭐ on GitHub.
