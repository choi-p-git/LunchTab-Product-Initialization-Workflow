# Card Readers

- Source PDF: `Card Readers _ Lunchtab Admin Help Center.pdf`
- Page count: 8
- Extracted at: 2026-07-18T16:56:29

## Page 1

Lunchtab supports card reader peripherals for processing card payments directly at the point of sale. The steps for conﬁguring and using card readers are speciﬁc to the conﬁgured pay- ment gateway. Please refer to the relevant documentation for your payment gateway below. We support Stripe Terminal smart readers that are compatible with server-driven inte- grations. This includes: • Stripe Reader S700 • Stripe Reader S710 • BBPOS WisePOS Note that not all readers are supported in every territory. Details of support by territory can be found in the Stripe Terminal documentation . Please feel free to reach out if you have any questions regarding compatibility before ordering any devices. While the Lunchtab POS is able to handle intermittent internet connectivity for most op- erations, it is critical when processing card payments that both the POS and the card reader have a stable internet connection. Where possible, we recommend using a wired Ethernet connection for both devices to ensure the most reliable connection. This may require the use of a dock or USB to Ethernet adapter for the card reader device. Stripe have speciﬁc Network Requirements for card reader devices. Please review Stripe Supported Devices Connectivity Card Readers

## Page 2

their documentation to ensure your network is compatible and to ﬁnd information on troubleshooting connectivity issues. In order to process payments with Stripe Terminal card readers, they need to be as- signed to a location. Locations represent the physical place where your readers operate, and are managed within the Terminal Locations page of your Stripe dashboard. Press the Create Location button at the top of the locations view and enter the name and address details of the business location where your readers will be used. For full details on managing Locations in Stripe, please refer to the Manage Locations article in the Stripe documentation. To register the reader, open the Terminal Readers page of your Stripe dashboard and press the Register Reader button at the top of the view. You can register your device using either the pairing code shown on startup, or the se- rial number shown on the device / packaging. Provide a recognizable name for the de- vice and assign it to the location you created in the previous step. For full details on registering readers in Stripe, please refer to the Register Readers article in the Stripe documentation. Once the reader has been registered to your payment gateway account, you will need to assign it to the Lunchtab POS device that will be using it to process payments. To assign the reader, access the conﬁguration of the relevant POS from the Vending Outlets page of the admin portal and select the reader from the dropdown before pressing Submit. Managing Locations Register Card Reader Assign Reader to POS

## Page 3

Note that a reader can only be assigned to one POS at a time. To use the reader on a diﬀerent POS, you will ﬁrst need to remove the existing assignment. Once the card reader has been assigned to the POS, it will be displayed in the Payment tab of the POS settings. If the POS will primarily be using card payments, you can also set the card reader as the default payment method when checking out.

## Page 4

Processing card payments follows a similar process to other payment methods in the Lunchtab POS. Once the order is ready to be paid, either press the primary Pay button if the card reader is selected as the default payment method, or use the payment methods selec- tor. The POS will then initialize the payment with the payment gateway service and await presentation of the card on the reader. The reader will present to the amount to the customer and be ready to accept contactless payments, or chip & PIN. Once the card has been successfully charged, the POS will complete the checkout process and will be ready to serve the next customer. In the event of a failed payment, the POS will display an error message with details of the failure. Processing Payments

## Page 5

You have the option to either Retry, which will allow the customer to reattempt with an- other card or PIN, or Cancel to return to the checkout view and optionally process the payment using cash or another payment method. We support the following device which integrates with the Blackbaud Merchant Services platform: • BBPOS WisePOS Note that Lunchtab does not support Blackbaud's Recurring Payments feature via the Payment Terminal. Please see Blackbaud's documentation for more information To register the reader open the Blackboard Payment Portal , navigate to the Terminal Devices -> Register Terminals section and click Register a terminal. Here you will need to generate a pairing code and follow the instructions on the screen of the terminal. Blackbaud Merchant Services Supported Devices Register Card Reader

## Page 6

Once the reader has been registered to your payment gateway account, you will need to assign it to the Lunchtab POS device that will be using it to process payments. To assign the reader, access the conﬁguration of the relevant POS from the Vending Outlets page of the admin portal and select the reader from the dropdown before pressing Submit. Note that a reader can only be assigned to one POS at a time. To use the reader on a diﬀerent POS, you will ﬁrst need to remove the existing assignment. Once the card reader has been assigned to the POS, it will be displayed in the Payment tab of the POS settings. Assign Reader to POS

## Page 7

If the POS will primarily be using card payments, you can also set the card reader as the default payment method when checking out. Processing card payments follows a similar process to other payment methods in the Lunchtab POS. Once the order is ready to be paid, either press the primary Pay button if the card reader is selected as the default payment method, or use the payment methods selec- tor. The POS will then initialize the payment with the payment gateway service and await presentation of the card on the reader. The reader will present to the amount to the customer and be ready to accept contactless payments, or chip & PIN. Follow the instructions on screen to complete the payment. Processing Payments

## Page 8

Once the card has been successfully charged, the POS will complete the checkout process and will be ready to serve the next customer. Copyright © 2026 Lunchtab Inc.
