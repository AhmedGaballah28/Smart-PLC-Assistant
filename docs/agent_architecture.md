# Smart PLC Assistant: Agent Architecture & Flow

This diagram illustrates how the 8 core agents connect to each other, the factory, and the databases. The pipeline is orchestrated by LangGraph's conditional edges — there is no separate supervisor node.

```mermaid
graph TD
    %% Define External Components
    Factory((Factory I/O\nPLC Sensors))
    SQLite[(SQLite DB\nState & Audit)]
    VectorDB[(ChromaDB\nKnowledge Base)]
    Reports[(data/reports/\nMD + JSON Files)]

    %% Core Pipeline Agents
    Monitor[Monitor Agent]
    Diagnostic[Diagnostic Agent]
    Repair[Repair Agent]
    Validation[Validation Agent]
    Simulation[Simulation Agent]
    Human[Human-in-the-Loop]
    Execution[Execution Agent]
    Report[Report Agent]

    %% Feedback Loop
    InjectFeedback[Inject Feedback]

    %% Real-time Monitoring Flow
    Factory -- "1. Raw Telemetry/Status" --> Monitor
    Monitor -- "2. Anomaly Alert" --> Diagnostic

    %% RAG Connections
    Diagnostic -- "Query Symptoms" --> VectorDB
    VectorDB -. "Troubleshooting Context & Scenarios" .-> Diagnostic
    Repair -- "Query Fixes" --> VectorDB
    VectorDB -. "Repair Bounds & Limits" .-> Repair
    Validation -- "Query Safe Ranges" --> VectorDB
    VectorDB -. "Safety Limits" .-> Validation
    Report -- "Query Specs" --> VectorDB
    VectorDB -. "Factory Context for Recommendations" .-> Report

    %% Core Intelligence Pipeline
    Diagnostic -- "3. Root Cause Report" --> Repair
    Repair -- "4. Repair Proposals" --> Validation
    Validation -- "5a. PASS" --> Simulation
    Validation -- "5b. FAIL (retries left)" --> InjectFeedback
    Validation -- "5c. FAIL (max retries)" --> Report
    Simulation -- "6. Prediction & Impact" --> Human

    %% Approval & Execution Flow
    Human -- "7a. APPROVE" --> Execution
    Human -- "7b. REJECT (retries left)" --> InjectFeedback
    Human -- "7c. REJECT (max retries)" --> Report
    Execution -- "8. Execute Commands" --> Factory
    Execution -- "9. Post-Execution" --> Report

    %% Feedback Loop
    InjectFeedback -- "Retry with Feedback" --> Repair

    %% Report Output
    Report -- "10. Save MD + JSON Reports" --> Reports

    %% Future Improvement
    Optimizer[Optimization Agent\nFuture Improvement]
    SQLite -. "Historical Incident Data" .-> Optimizer
    Optimizer -. "Advisory Recommendations" .-> Monitor

    %% Database Writes
    Monitor -. "Logs Anomalies" .-> SQLite
    Diagnostic -. "Logs Diagnosis" .-> SQLite
    Repair -. "Logs Proposals" .-> SQLite
    Validation -. "Logs Verdict" .-> SQLite
    Simulation -. "Logs Prediction" .-> SQLite
    Execution -. "Logs Audit Trail" .-> SQLite

    %% Styling
    classDef agent fill:#0f4c75,stroke:#3282b8,stroke-width:2px,color:#fff;
    classDef factory fill:#b83b5e,stroke:#fff,stroke-width:2px,color:#fff;
    classDef db fill:#f0a500,stroke:#fff,stroke-width:2px,color:#000;
    classDef report fill:#2d6a4f,stroke:#52b788,stroke-width:2px,color:#fff;
    classDef output fill:#6c757d,stroke:#fff,stroke-width:2px,color:#fff;
    classDef feedback fill:#5c5c5c,stroke:#aaa,stroke-width:1px,color:#fff,stroke-dasharray: 5 5;
    classDef future fill:#5c5c5c,stroke:#fff,stroke-width:1px,color:#fff,stroke-dasharray: 5 5;

    class Monitor,Diagnostic,Repair,Validation,Simulation,Human,Execution agent;
    class Factory factory;
    class SQLite,VectorDB db;
    class Report report;
    class Reports output;
    class InjectFeedback feedback;
    class Optimizer future;
```
