# workpulse-ai-monitor
WorkPulse is a Python-based employee activity monitoring system with Firebase integration. It tracks activity, logs check-ins, detects meetings (Zoom, Teams, Google Meet, etc.) to avoid interruptions, stores data in the cloud, and generates analytics dashboards for employee engagement reporting.


# WorkPulse – Intelligent Employee Activity Monitoring System

WorkPulse is a Python-based employee activity monitoring and analytics platform that uses cloud storage, automated check-ins, and meeting-aware scheduling to measure employee engagement and responsiveness.

Unlike traditional monitoring tools, WorkPulse includes an intelligent meeting-detection system. Before displaying a check-in prompt, the system analyzes active applications, browser windows, and optional calendar events to determine whether the employee is currently participating in a meeting. If a meeting is detected, the check-in is automatically postponed to avoid interrupting important work.

## Key Features

* Firebase Firestore cloud database integration
* Intelligent meeting detection and interruption avoidance
* Automated employee check-ins
* Keyboardmake this in35m0 and mouse activity tracking
* Idle-time analysis
* AI-generated personalized questions based on employee interests
* Cloud-based session and activity logging
* Real-time reporting dashboard
* Presence and responsiveness analytics
* Cross-platform Python implementation

## Intelligent Meeting Awareness

The system automatically detects:

* Zoom meetings
* Microsoft Teams meetings
* Google Meet sessions
* Webex meetings
* Slack Huddles
* Discord voice calls
* Calendar-based meetings (optional)

When a meeting is detected, WorkPulse postpones employee check-ins and records the reason, ensuring minimal disruption to workflow.

## Technologies

* Python
* Firebase Firestore
* Firebase Admin SDK
* Tkinter
* Psutil
* Pynput
* Requests
* Python-Dotenv
* Rich Dashboard

## Project Goal

The project demonstrates cloud integration, desktop monitoring, activity analytics, meeting-aware automation, and Python application development. It was developed as a portfolio and learning project to explore employee engagement analytics and intelligent workflow monitoring.




<img width="1269" height="482" alt="image" src="https://github.com/user-attachments/assets/54002581-f26e-4b0d-a67b-485819950f15" />
