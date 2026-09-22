"""
Constants for the Staff Movement (Field Visit / Movement Log) module.
Includes static AMC clients, service/repair checkboxes, and government/corporate departments.
"""

AMC_CLIENTS = [
    "Tribhuvan International Airport (TIA)",
    "Ministry of Forests and Environment",
    "Ministry of Youth and Sports",
    "Department of Agriculture (कृषि विभाग)",
    "Infrastructure Development",
    "Federal Secretariat Construction and Management Office (FSCMO)",
    "Central Agriculture",
    "Office of the Prime Minister and Council of Ministers (OPMCM)",
    "National Identity Card and Civil Registration Department (NIDCRD)",
    "Department of Information Technology (DoIT)",
    "Ministry of Law, Justice and Parliamentary Affairs",
    "Chandragiri Municipality",
    "Office of the President of Nepal",
    "Department of Tourism",
    "Panchashil Multipurpose Co-operative Ltd.",
    "Project Directorate (ADB)",
    "Ministry of Physical Infrastructure and Transport (MoPIT)",
]

SERVICE_REPAIR_SUPPORT = [
    "Desktop Repair",
    "Laptop Repair",
    "Printer Repair",
    "Photocopy Machine Repair",
    "AC Repair",
    "Network problem",
    "Telephone problem",
    "Electricity Repair",
    "CCTV Repair",
]

SERVICE_SETUP_INSTALL = [
    "AP setup",
    "Network Setup",
    "Telephone setup",
    "Electrical Points setup",
    "CCTV installation and configuration",
    "Desktop setup",
    "Laptop setup",
]

SERVICE_CHECKBOXES = SERVICE_REPAIR_SUPPORT + SERVICE_SETUP_INSTALL

DEPARTMENT_CHOICES = [
    "Administration (प्रशासन)",
    "Accounts (लेखा)",
    "Store (जिन्सी)",
    "Sachiwalaya (सचिवालय)",
    "Meeting Hall (सभा हल)",
    "Law (कानुन)",
    "Beruju (बेरुजु)",
    "IT (सूचना प्रविधि)",
    "Secretary Office (सचिव)",
    "Joint-Secretary (सहसचिव)",
    "Under-Secretary (उपसचिव)",
    "Section Office (शाखा अधिकृत )",
    "Senior Assistant (नायब सुब्बा)",
]
