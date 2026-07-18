# Initial Vending Outlet Setup

- Source PDF: `Initial Vending Outlet Setup _ Lunchtab Admin Help Center.pdf`
- Page count: 4
- Extracted at: 2026-07-18T16:56:29

## Page 1

Vending outlets represent the physical devices where you process product sales and ac- cept cash account charges to family accounts. The Vending Outlets page in the admin portal facilitates the registration and man- agement of vending outlets. Before registering a new vending outlet, the application must be installed. The Lunchtab POS application supports the Windows 10 and 11 operating systems. To download the application installer, select Download Installer from the actions menu on the Vending Outlets page. Cashiers without the system admin role will be unable to access this view, but can download the latest installer from the Cashier tab of their Account Settings . For the application to function correctly, the POS must be able to send and receive data to and from the Lunchtab servers and the Microsoft Azure SignalR Service. If your network is protected by a ﬁrewall, please ensure that the following domains are whitelisted: • *.lunchtab.app • *.signalr.net Please ensure that port 5671 is open on your ﬁrewall as this is required by traﬃc be- tween the POS and the Lunchtab servers. POS App Installation If each cashier will be using their own Windows login, the installer must be run for each Windows account. Registration will only be required once per vending outlet. Multiple Windows Users Connectivity / Firewall Conﬁguration Initial Vending Outlet Setup

## Page 2

Once the application is installed, it will launch to the registration screen if it has not been registered previously. Value Description Device Name A name for the vending outlet. Host Name The host name for your school. For example, if your school is hosted at exampleschool.lunchtab.com , your host name is exampleschool . Type The type of vending outlet to register. See Vending Outlet Types for further information. Once the registration has been initiated, the vending outlet will appear in the Vending Registration

## Page 3

Outlets page in the admin portal. Open the details for the vending outlet, and make a note of the displayed registration code. This code should be entered into the screen on the vending outlet to complete the registration process. Once registration has completed, the vending outlet will perform an initial data sync and then be ready to log in. For details on conﬁguring cashier credentials and logging in, see Cashier Login. The Point of Sale vending outlet is used to process sales of products and perform some management tasks related to users. The Pay Station vending outlet type is used to apply cash account charges to family ac- counts. These vending outlets will need to be connected to a bill acceptor device to ac- cept cash notes. Vending Outlet Types Point Of Sale Pay Station

## Page 4

Copyright © 2026 Lunchtab Inc.
