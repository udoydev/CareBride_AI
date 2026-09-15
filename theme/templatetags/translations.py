from django import template
from django.utils.safestring import mark_safe

register = template.Library()

TRANSLATIONS = {
    "Dashboard": {"bn": "ড্যাশবোর্ড"},
    "Home": {"bn": "হোম"},
    "Doses": {"bn": "ওষুধ"},
    "Records": {"bn": "রেকর্ড"},
    "Follow-up": {"bn": "ফলো-আপ"},
    "Appointments": {"bn": "অ্যাপয়েন্টমেন্ট"},
    "Analytics": {"bn": "অ্যানালিটিক্স"},
    "Doctors": {"bn": "ডাক্তার"},
    "Profile": {"bn": "প্রোফাইল"},
    "Log out": {"bn": "লগ আউট"},
    "Sign Out": {"bn": "সাইন আউট"},
    "Login": {"bn": "লগ ইন"},
    "Sign In": {"bn": "সাইন ইন"},
    "Sign Up": {"bn": "সাইন আপ"},
    "Get started": {"bn": "শুরু করুন"},
    "Welcome back": {"bn": "ফিরে এসেছেন"},
    "Create your account": {"bn": "আপনার অ্যাকাউন্ট খুলুন"},
    "Registration": {"bn": "অ্যাকাউন্ট তৈরি করুন"},
    "Account access": {"bn": "অ্যাকাউন্ট লগইন"},
    "Email Address": {"bn": "ইমেইল অ্যাড্রেস"},
    "Password": {"bn": "পাসওয়ার্ড"},
    "Forgot password?": {"bn": "পাসওয়ার্ড ভুলে গেছেন?"},
    "Log in with Email": {"bn": "লগ ইন করুন"},
    "New here?": {"bn": "নতুন অ্যাকাউন্ট খুলবেন?"},
    "Create an account": {"bn": "অ্যাকাউন্ট তৈরি করুন"},
    "First name": {"bn": "নামের প্রথমাংশ"},
    "Last name": {"bn": "নামের শেষাংশ"},
    "Email address (Login ID)": {"bn": "ইমেইল অ্যাড্রেস (লগইন 아이ডি)"},
    "Bangladeshi mobile number": {"bn": "বাংলাদেশি মোবাইল নম্বর"},
    "Confirm Password": {"bn": "পাসওয়ার্ড নিশ্চিত করুন"},
    "Account Type": {"bn": "অ্যাকাউন্টের ধরন"},
    "Doctor Verification & Professional Details": {"bn": "ডাক্তার ভেরিফিকেশন ও পেশাগত তথ্য"},
    "Years of Experience (Required)": {"bn": "অভিজ্ঞতার বছর (বাধ্যতামূলক)"},
    "Consultation Fee BDT (Required)": {"bn": "পরামর্শ চার্জ BDT (বাধ্যতামূলক)"},
    "Specialty (Required)": {"bn": "বিশেষতা (বাধ্যতামূলক)"},
    "Upload BMDC License / Certificate (Required)": {"bn": "বিএমডিসি লাইসেন্স / সার্টিফিকেট আপলোড করুন (বাধ্যতামূলক)"},
    "Patient Identity Verification (BD Document Upload)": {"bn": "রোগী নাগরিক ভেরিফিকেশন (পরিচয়পত্র আপলোড)"},
    "District (Bangladesh)": {"bn": "জেলা / District"},
    "Upload NID Card, Birth Certificate, or Passport (Image/PDF)": {"bn": "এনআইডি কার্ড বা জন্ম সনদের ছবি/পিডিএফ আপলোড করুন"},
    "Document proof for offline in-person chamber consultation safety.": {"bn": "অফলাইন চেম্বার অ্যাপয়েন্টমেন্ট নিরাপত্তার জন্য ডকুমেন্ট প্রমাণপত্র গ্রহণ করা হয়।"},
    "Create BD Account": {"bn": "অ্যাকাউন্ট তৈরি করুন"},
    "Already have an account?": {"bn": "ইতিমধ্যে অ্যাকাউন্ট আছে?"},
    "Log in with Email": {"bn": "লগ ইন করুন"},
    "Your Health Companion": {"bn": "স্বাস্থ্য সহায়ক"},
    "Prescriptions, reminders, and doctors — all in one place.": {"bn": "প্রেসক্রিপশন, রিমাইন্ডার, ডাক্তার — সব এক প্ল্যাটফর্মে।"},
    "CareBridge AI translates prescriptions into plain language, reminds you about medicines, and helps book doctor appointments.": {"bn": "CareBridge AI প্রেসক্রিপশনকে সহজ ভাষায় অনুবাদ করে, ওষুধের সময় মনে দেয় এবং ডাক্তারের অ্যাপয়েন্টমেন্ট বুকিং করে।"},
    "Start as Patient": {"bn": "রোগী হিসেবে শুরু করুন"},
    "Join as Doctor": {"bn": "ডাক্তার হিসেবে যোগ দিন"},
    "Bangla + English": {"bn": "বাংলা + ইংরেজি"},
    "Voice Support": {"bn": "ভয়েস সাপোর্ট"},
    "Free to use": {"bn": "ফ্রি"},
    "Prescription": {"bn": "প্রেসক্রিপশন"},
    "Prescription preview": {"bn": "প্রেসক্রিপশন প্রিভিউ"},
    "Patient Info": {"bn": "রোগীর তথ্য"},
    "Patient photo": {"bn": "রোগীর ছবি"},
    "AI Advice": {"bn": "AI পরামর্শ"},
    "How it works": {"bn": "কাজ করে কীভাবে"},
    "1. Register": {"bn": "১. নিবন্ধন করুন"},
    "Create a free account as a patient or doctor.": {"bn": "ফ্রি অ্যাকাউন্ট তৈরি করুন রোগী বা ডাক্তার হিসেবে।"},
    "2. Add Prescription": {"bn": "২. প্রেসক্রিপশন যোগ করুন"},
    "Upload your doctor's prescription or connect digitally.": {"bn": "ডাক্তারের প্রেসক্রিপশন আপলোড করুন বা ডিজিটালি সংযোগ করুন।"},
    "3. Get AI Explanation": {"bn": "৩. AI ব্যাখ্যা পান"},
    "Hear your prescription in simple Bangla or English.": {"bn": "প্রেসক্রিপশনকে সহজ বাংলায় বা ইংরেজিতে শুনুন।"},
    "4. Follow Up": {"bn": "৪. ফলো-আপ করুন"},
    "Track reminders and appointments automatically.": {"bn": "রিমাইন্ডার ও অ্যাপয়েন্টমেন্ট স্বয়ংক্রিয়ভাবে ট্র্যাক করুন।"},
    "Features": {"bn": "ফিচার"},
    "Plain Language": {"bn": "সহজ ব্যাখ্যা"},
    "Translate prescriptions into simple Bangla or English.": {"bn": "প্রেসক্রিপশনকে সহজ বাংলায় বা ইংরেজিতে অনুবাদ করুন।"},
    "Dose Reminders": {"bn": "ডোজ রিমাইন্ডার"},
    "Never miss a dose with smart reminders.": {"bn": "ওষুধের সময় স্মরণ করুন, কোনো ডোজ মিস না করুন।"},
    "Appointments": {"bn": "অ্যাপয়েন্টমেন্ট"},
    "Book and track doctor appointments easily.": {"bn": "ডাক্তারের অ্যাপয়েন্টমেন্ট বুক করুন এবং ট্র্যাক করুন।"},
    "Voice Support": {"bn": "ভয়েস সাপোর্ট"},
    "Listen to prescriptions and navigate with voice commands.": {"bn": "প্রেসক্রিপশন শুনুন এবং ভয়েস কম্যান্ড দিয়ে নেভিগেট করুন।"},
    "For Doctors": {"bn": "ডাক্তারের জন্য"},
    "Track patient adherence and manage appointments.": {"bn": "রোগীর অ্যাডহেরেন্স ট্র্যাক করুন এবং অ্যাপয়েন্টমেন্ট ম্যানেজ করুন।"},
    "Secure": {"bn": "নিরাপত্তা"},
    "Your health data is encrypted and secure.": {"bn": "আপনার স্বাস্থ্য তথ্য এনক্রিপ্টেড এবং সুরক্ষিত।"},
    "Help": {"bn": "সহায়তা"},
    "Ask Us Anything": {"bn": "জিজ্ঞাসা করুন"},
    "Here are some common questions and answers.": {"bn": "নিচের কিছু সাধারণ প্রশ্ন এবং উত্তর দেখুন।"},
    "What is CareBridge AI?": {"bn": "CareBridge AI কি?"},
    "CareBridge AI is a health platform that translates prescriptions into plain language, provides medicine reminders, and helps book doctor appointments.": {"bn": "CareBridge AI একটি স্বাস্থ্য প্ল্যাটফর্ম যা প্রেসক্রিপশনকে সহজ ভাষায় অনুবাদ করে, ওষুধের রিমাইন্ডার দেয় এবং ডাক্তারের অ্যাপয়েন্টমেন্ট বুকিং করে।"},
    "What services do you offer?": {"bn": "কি কি সেবা আপনাকে দিতে পারে?"},
    "We provide prescription translation, medicine reminders, doctor booking, health records, and AI chat services.": {"bn": "প্রেসক্রিপশন অনুবাদ, ওষুধের রিমাইন্ডার, ডাক্তার বুকিং, স্বাস্থ্য রেকর্ড, এবং AI চ্যাট সেবা প্রদান করি।"},
    "How do I get started?": {"bn": "কিভাবে শুরু করব?"},
    "Click the \"Start as Patient\" or \"Join as Doctor\" button below to register.": {"bn": "নিচের \"রোগী হিসেবে শুরু করুন\" বা \"ডাক্তার হিসেবে যোগ দিন\" বাটন ক্লিক করে রেজিস্ট্রেশন করুন।"},
    "Your prescription, now in your hands.": {"bn": "আপনার প্রেসক্রিপশন, এখন আপনার হাতে।"},
    "Everything you need to manage your health": {"bn": "আপনার স্বাস্থ্য ব্যবস্থাপনার প্রয়োজনীয় সবকিছু।"},
    "Get started": {"bn": "শুরু করুন"},
    "Your health, simplified.": {"bn": "আপনার স্বাস্থ্য, এখন আরও সহজ।"},
    "Free for patients. Create your account today.": {"bn": "রোগীদের জন্য ফ্রি। আজই অ্যাকাউন্ট তৈরি করুন।"},
    "Create Account": {"bn": "অ্যাকাউন্ট তৈরি করুন"},
    "Log in": {"bn": "লগ ইন"},
    "Patient dashboard": {"bn": "রোগীর ড্যাশবোর্ড"},
    "Today's Snapshot": {"bn": "আজকের সারাংশ"},
    "Your doses and next follow-up at a glance.": {"bn": "আপনার ওষুধ এবং পরবর্তী ফলো-আপ এক নজরে।"},
    "Doses": {"bn": "ডোজ"},
    "Doses due today": {"bn": "আজকের ওষুধ"},
    "View checklist": {"bn": "চেকলিস্ট দেখুন"},
    "Set custom dose times": {"bn": "ডোজ টাইম সেট করুন"},
    "Follow-up": {"bn": "ফলো-আপ"},
    "Next follow-up": {"bn": "পরবর্তী ফলো-আপ"},
    "No upcoming follow-up.": {"bn": "কোনো আসন্ন ফলো-আপ নেই।"},
    "View all follow-ups": {"bn": "সব ফলো-আপ দেখুন"},
    "Book your first appointment to get started": {"bn": "আপনার প্রথম অ্যাপয়েন্টমেন্ট বুক করুন"},
    "Select a doctor and start your health journey today.": {"bn": "অনুগ্রহ করে একজন ডাক্তার নির্বাচন করে আপনার স্বাস্থ্য যাত্রা শুরু করুন।"},
    "Find a Doctor": {"bn": "ডাক্তার খুঁজুন"},
    "Appointments": {"bn": "অ্যাপয়েন্টমেন্ট"},
    "Upcoming Appointments": {"bn": "আসন্ন অ্যাপয়েন্টমেন্ট"},
    "No upcoming appointments.": {"bn": "কোনো আসন্ন অ্যাপয়েন্টমেন্ট নেই।"},
    "View all appointments": {"bn": "সব অ্যাপয়েন্টমেন্ট দেখুন"},
    "Refunds & Cancellations": {"bn": "রিফান্ড ও ক্যান্সেলেশন"},
    "Your Updates": {"bn": "আপনার আপডেট"},
    "All notifications": {"bn": "সমস্ত নোটিফিকেশন"},
    "Health Calendar": {"bn": "স্বাস্থ্য ক্যালেন্ডার"},
    "Today": {"bn": "আজ"},
    "Upcoming Follow-up": {"bn": "আসন্ন ফলো-আপ"},
    "View": {"bn": "দেখুন"},
    "View Details": {"bn": "বিস্তারিত দেখুন"},
    "Cancel": {"bn": "বাতিল"},
    "Edit": {"bn": "সম্পাদনা"},
    "No appointments found.": {"bn": "কোনো অ্যাপয়েন্টমেন্ট পাওয়া যায়নি।"},
    "All": {"bn": "সব"},
    "Pending": {"bn": "অপেক্ষাম Rowe"},
    "Confirmed": {"bn": "নিশ্চিত"},
    "Completed": {"bn": "সম্পূর্ণ"},
    "Cancelled": {"bn": "বাতিল"},
    "Visited": {"bn": "পরিদর্শন"},
    "Missed": {"bn": "মিস"},
    "Manage": {"bn": "পরিচালনা"},
    "My appointments": {"bn": "আমার অ্যাপয়েন্টমেন্ট"},
    "Export Payments": {"bn": "পেমেন্ট এক্সপোর্ট"},
    "My analytics": {"bn": "আমার এনালিটিক্স"},
    "Health Dashboard": {"bn": "স্বাস্থ্য ড্যাশবোর্ড"},
    "Your appointments, spending, and health metrics at a glance.": {"bn": "আপনার অ্যাপয়েন্টমেন্ট, ব্যয়, এবং স্বাস্থ্য মেট্রিক্স এক নজরে।"},
    "Total Appointments": {"bn": "মোট অ্যাপয়েন্টমেন্ট"},
    "Completed": {"bn": "সম্পূর্ণ"},
    "Total Spent": {"bn": "মোট ব্যয়"},
    "Pending Payments": {"bn": "অপেক্ষাম Rowe পেমেন্ট"},
    "Upcoming": {"bn": "আসন্ন"},
    "Prescriptions": {"bn": "প্রেসক্রিপশন"},
    "Follow-ups": {"bn": "ফলো-আপ"},
    "Recent Appointments": {"bn": "সাম্প্রতিক অ্যাপয়েন্টমেন্ট"},
    "Recent Prescriptions": {"bn": "সাম্প্রতিক প্রেসক্রিপশন"},
    "View health records": {"bn": "স্বাস্থ্য রেকর্ড দেখুন"},
    "No appointments yet.": {"bn": "এখনও কোনো অ্যাপয়েন্টমেন্ট নেই।"},
    "No prescriptions yet.": {"bn": "এখনও কোনো প্রেসক্রিপশন নেই।"},
    "Doctor Dashboard": {"bn": "ডাক্তার ড্যাশবোর্ড"},
    "Your patients, schedule, and appointments at a glance.": {"bn": "আপনার রোগী, সময়সূচী, এবং অ্যাপয়েন্টমেন্ট এক নজরে।"},
    "Total Patients": {"bn": "মোট রোগী"},
    "Today's Appointments": {"bn": "আজকের অ্যাপয়েন্টমেন্ট"},
    "Pending Confirmations": {"bn": "অপেক্ষাম Rowe নিশ্চিত"},
    "Upcoming Follow-ups": {"bn": "আসন্ন ফলো-আপ"},
    "Set Time Slots": {"bn": "সময় স্লট সেট করুন"},
    "Configure your weekly availability": {"bn": "সাপ্তাহিক আপনার প্রাপ্ততা কনফিগার করুন"},
    "View Appointments": {"bn": "অ্যাপয়েন্টমেন্ট দেখুন"},
    "Manage patient bookings": {"bn": "রোগীর বুকিং পরিচালনা করুন"},
    "Find Patients": {"bn": "রোগী খুঁজুন"},
    "Search and view patient records": {"bn": "রোগীর রেকর্ড অনুসন্ধান এবং দেখুন"},
    "Refund & Cancellation Updates": {"bn": "রিফান্ড ও ক্যান্সেলেশন আপডেট"},
    "View all notifications": {"bn": "সমস্ত নোটিফিকেশন দেখুন"},
    "No active patients or follow-ups yet.": {"bn": "এখনও কোনো সক্রিয় রোগী বা ফলো-আপ নেই।"},
    "Patients": {"bn": "রোগীদের তালিকা"},
    "Search Patients": {"bn": "রোগী অনুসন্ধান"},
    "Search by name or phone number": {"bn": "নাম বা ফোন নম্বর দিয়ে অনুসন্ধান করুন"},
    "No patients found.": {"bn": "কোনো রোগী পাওয়া যায়নি।"},
    "View File →": {"bn": "ফাইল দেখুন →"},
    "All Appointments": {"bn": "সমস্ত অ্যাপয়েন্টমেন্ট"},
    "You have appointment(s) today.": {"bn": "আজকের আপনার অ্যাপয়েন্টমেন্ট আছে।"},
    "Appointment Report": {"bn": "অ্যাপয়েন্টমেন্ট রিপোর্ট"},
    "Export Financial Report": {"bn": "আর্থিক রিপোর্ট এক্সপোর্ট"},
    "Emergency Alert": {"bn": "জরুরি সতর্কতা"},
    "Total": {"bn": "মোট"},
    "Visited": {"bn": "পরিদর্শন"},
    "Pending Approval": {"bn": "অনুমোদনের অপেক্ষায়"},
    "Auto-Detect Missed": {"bn": "মিস অটো-ডিটেক্ট"},
    "No appointments found.": {"bn": "কোনো অ্যাপয়েন্টমেন্ট পাওয়া যায়নি।"},
    "No appointments found.": {"bn": "কোনো অ্যাপয়েন্টমেন্ট পাওয়া যায়নি।"},
    "No appointments found.": {"bn": "কোনো অ্যাপয়েন্টমেন্ট পাওয়া যায়নি।"},
    "Appointment #": {"bn": "অ্যাপয়েন্টমেন্ট #"},
    "Back to appointments": {"bn": "অ্যাপয়েন্টমেন্টে ফিরে যান"},
    "Date": {"bn": "তারিখ"},
    "Time": {"bn": "সময়"},
    "Type": {"bn": "প্রকার"},
    "Fee": {"bn": "ফি"},
    "Platform Fee (15%)": {"bn": "প্ল্যাটফর্ম ফি (১৫%)"},
    "Refund": {"bn": "রিফান্ড"},
    "Chief Complaint": {"bn": "প্রধান অভিযোগ"},
    "Pay Now": {"bn": "এখন পে করুন"},
    "Payment Required": {"bn": "পেমেন্ট প্রয়োজন"},
    "Paid": {"bn": "পেইড"},
    "Waiting for doctor confirmation": {"bn": "ডাক্তারের নিশ্চিতকরণের অপেক্ষায়"},
    "The doctor will confirm your appointment shortly. You will receive a notification when confirmed.": {"bn": "ডাক্তার শীঘ্রই আপনার অ্যাপয়েন্টমেন্ট নিশ্চিত করবেন। নিশ্চিত হলে আপনি বিজ্ঞপ্তি পাবেন।"},
    "Download Receipt": {"bn": "রসিদ ডাউনলোড"},
    "Cancel Appointment": {"bn": "অ্যাপয়েন্টমেন্ট বাতিল"},
    "Edit Booking": {"bn": "বুকিং সম্পাদনা"},
    "Cancellation Request Pending": {"bn": "ক্যান্সেলেশন অনুরোধ মুলতুলি"},
    "Your cancellation request is being reviewed by the doctor. You will be notified once decided.": {"bn": "আপনার বাতিলের অনুরোধ ডাক্তার কর্তৃক পর্যালোচনা করা হচ্ছে। সিদ্ধান্ত নিলে আপনাকে জানানো হবে।"},
    "Review Cancellation Request": {"bn": "বাতিলের অনুরোধ পর্যালোচনা করুন"},
    "Patient": {"bn": "রোগী"},
    "Reason": {"bn": "কারণ"},
    "Approve": {"bn": "অনুমোদন"},
    "Reject": {"bn": "প্রত্যাখ্যান"},
    "Request Cancellation": {"bn": "বাতিলের অনুরোধ"},
    "Reason for cancellation": {"bn": "বাতিলের কারণ"},
    "Please explain why you need to cancel...": {"bn": "অনুগ্রহ করে বাতিল করার কারণ ব্যাখ্যা করুন..."},
    "Update Appointment": {"bn": "অ্যাপয়েন্টমেন্ট আপডেট"},
    "Edit appointment": {"bn": "অ্যাপয়েন্টমেন্ট সম্পাদনা"},
    "Weekly Availability": {"bn": "সাপ্তাহিক প্রাপ্ততা"},
    "Available Time Slots": {"bn": "উপলব্ধ সময় স্লট"},
    "Select a new date and time to reschedule.": {"bn": "পুনরায় সময়সূচির জন্য একটি নতুন তারিখ এবং সময় নির্বাচন করুন।"},
    "Consultation Type": {"bn": "পরামর্শের ধরন"},
    "In-Person Chamber": {"bn": "প্রসensed Chamber"},
    "No available slots at the moment.": {"bn": "মুদ্র Guine última স্লট নেই।"},
    "Save Changes": {"bn": "পরিবর্তন সংরক্ষণ করুন"},
    "My appointments": {"bn": "আমার অ্যাপয়েন্টমেন্ট"},
    "View all appointments": {"bn": "সব অ্যাপয়েন্টমেন্ট দেখুন"},
    "My analytics": {"bn": "আমার এনালিটিক্স"},
    "Health Dashboard": {"bn": "স্বাস্থ্য ড্যাশবোর্ড"},
    "Your appointments, spending, and health metrics at a glance.": {"bn": "আপনার অ্যাপয়েন্টমেন্ট, ব্যয়, এবং স্বাস্থ্য মেট্রিক্স এক নজরে।"},
    "Total Appointments": {"bn": "মোট অ্যাপয়েন্টমেন্ট"},
    "Completed": {"bn": "সম্পূর্ণ"},
    "Total Spent": {"bn": "মোট ব্যয়"},
    "Pending Payments": {"bn": "অপেক্ষাম Rowe পেমেন্ট"},
    "Upcoming": {"bn": "আসন্ন"},
    "Prescriptions": {"bn": "প্রেসক্রিপশন"},
    "Follow-ups": {"bn": "ফলো-আপ"},
    "Recent Appointments": {"bn": "সাম্প্রতিক অ্যাপয়েন্টমেন্ট"},
    "Recent Prescriptions": {"bn": "সাম্প্রতিক প্রেসক্রিপশন"},
    "View health records": {"bn": "স্বাস্থ্য রেকর্ড দেখুন"},
    "No appointments yet.": {"bn": "এখনও কোনো অ্যাপয়েন্টমেন্ট নেই।"},
    "No prescriptions yet.": {"bn": "এখনও কোনো প্রেসক্রিপশন নেই।"},
    "Platform Overview": {"bn": "প্ল্যাটফর্ম ওভারভিউ"},
    "Total Doctors": {"bn": "মোট ডাক্তার"},
    "Total Patients": {"bn": "মোট রোগী"},
    "Total Revenue": {"bn": "মোট আয়"},
    "Net Profit": {"bn": "নিট প্রফিট"},
    "Platform fee: 15% per booking": {"bn": "প্ল্যাটফর্ম ফি: প্রতি বুকিং ১৫%"},
    "After refunds": {"bn": "রিফান্ড পরবর্তী"},
    "Total": {"bn": "মোট"},
    "Pending": {"bn": "অপেক্ষাম Rowe"},
    "Confirmed": {"bn": "নিশ্চিত"},
    "Visited": {"bn": "পরিদর্শন"},
    "Missed": {"bn": "মিস"},
    "Cancelled": {"bn": "বাতিল"},
    "Pending Approval": {"bn": "অনুমোদনের অপেক্ষায়"},
    "Total Refunds": {"bn": "মোট রিফান্ড"},
    "Platform Fees": {"bn": "প্ল্যাটফর্ম ফি"},
    "Avg per Doctor": {"bn": "প্রতি ডাক্তার গড়"},
    "Avg per Patient": {"bn": "প্রতি রোগী গড়"},
    "Active Schedules": {"bn": "সক্রিয় সময়সূচী"},
    "Prescriptions": {"bn": "প্রেসক্রিপশন"},
    "Notifications": {"bn": "নোটিফিকেশন"},
    "Consultation Type": {"bn": "পরামর্শের ধরন"},
    "in-person": {"bn": "ইন-পারসন"},
    "video": {"bn": "ভিডিও"},
    "Daily Appointments (Last 7 Days)": {"bn": "দৈনিক অ্যাপয়েন্টমেন্ট (গত ৭ দিন)"},
    "Recent Transactions": {"bn": "সাম্প্রতিক লেনদেন"},
    "No appointments yet.": {"bn": "এখনও কোনো অ্যাপয়েন্টমেন্ট নেই।"},
    "Admin Analytics": {"bn": "অ্যাডমিন এনালিটিক্স"},
    "Developer metadata for future feature planning and system health monitoring.": {"bn": "ভবিষ্যতের ফিচার পরিকল্পনা এবং সিস্টেম স্বাস্থ্য মনিটরিংয়ের জন্য ডেভেলপার মেটাডেটা।"},
    "Total Revenue": {"bn": "মোট আয়"},
    "BDT": {"bn": "BDT"},
    "this month": {"bn": "এই মাস"},
    "this week": {"bn": "এই সপ্তাহ"},
    "After refunds": {"bn": "রিফান্ড পরবর্তী"},
    "Total": {"bn": "মোট"},
    "Pending": {"bn": "অপেক্ষাম Rowe"},
    "Confirmed": {"bn": "নিশ্চিত"},
    "Visited": {"bn": "পরিদর্শন"},
    "Missed": {"bn": "মিস"},
    "Cancelled": {"bn": "বাতিল"},
    "Pending Approval": {"bn": "অনুমোদনের অপেক্ষায়"},
    "Total Refunds": {"bn": "মোট রিফান্ড"},
    "partial": {"bn": "আংশিক"},
    "full": {"bn": "সম্পূর্ণ"},
    "Platform Fees": {"bn": "প্ল্যাটফর্ম ফি"},
    "15% of all paid bookings": {"bn": "সমস্ত পেইড বুকিংয়ের ১৫%"},
    "Avg per Doctor": {"bn": "প্রতি ডাক্তার গড়"},
    "appointments": {"bn": "অ্যাপয়েন্টমেন্ট"},
    "Avg per Patient": {"bn": "প্রতি রোগী গড়"},
    "appointments": {"bn": "অ্যাপয়েন্টমেন্ট"},
    "Active Schedules": {"bn": "সক্রিয় সময়সূচী"},
    "doctor time slots configured": {"bn": "ডাক্তার সময় স্লট কনফিগার করা হয়েছে"},
    "Prescriptions": {"bn": "প্রেসক্রিপশন"},
    "follow-ups created": {"bn": "ফলো-আপ তৈরি হয়েছে"},
    "Notifications": {"bn": "নোটিফিকেশন"},
    "unread": {"bn": "অপঠিত"},
    "Consultation Type": {"bn": "পরামর্শের ধরন"},
    "in-person": {"bn": "ইন-পারসন"},
    "video": {"bn": "ভিডিও"},
    "Daily Appointments (Last 7 Days)": {"bn": "দৈনিক অ্যাপয়েন্টমেন্ট (গত ৭ দিন)"},
    "Recent Transactions": {"bn": "সাম্প্রতিক লেনদেন"},
    "Platform fee: 15% per booking": {"bn": "প্ল্যাটফর্ম ফি: প্রতি বুকিং ১৫%"},
    "No appointments yet.": {"bn": "এখনও কোনো অ্যাপয়েন্টমেন্ট নেই।"},
    "ID": {"bn": "আইডি"},
    "Patient": {"bn": "রোগী"},
    "Doctor": {"bn": "ডাক্তার"},
    "Date": {"bn": "তারিখ"},
    "Status": {"bn": "স্ট্যাটাস"},
    "Fee": {"bn": "ফি"},
    "Platform Fee": {"bn": "প্ল্যাটফর্ম ফি"},
    "Refund": {"bn": "রিফান্ড"},
    "Net Payout": {"bn": "নিট পেআউট"},
    "Session Expiring Soon": {"bn": "সেশনের সময় শেষ হবে"},
    "You will be logged out soon due to inactivity. Would you like to stay signed in?": {"bn": "আপনি ২ ঘণ্টা নিষ্ক্রিয় হবেন। অনুগ্রহপূর্বক আবার লগইন করুন।"},
    "Stay Logged In": {"bn": "লগইন থাকুন"},
    "Log Out": {"bn": "লগ আউট"},
    "Switch theme": {"bn": "থিম বদলান"},
    "Open navigation menu": {"bn": "নেভিগেশন খুলুন"},
    "Voice Navigation": {"bn": "ভয়েস নেভিগেশন"},
    "Voice Command": {"bn": "ভয়েস কমান্ড"},
    "Mark as visited?": {"bn": "পরিদর্শন হিসেবে চিহ্নিত করবেন?"},
    "Mark as missed? A notification will be sent to the patient.": {"bn": "মিস হিসেবে চিহ্নিত করবেন? রোগীকে বিজ্ঞপ্তি পাঠানো হবে।"},
    "Approve cancellation? 35% refund will be issued.": {"bn": "বাতিল অনুমোদন করবেন? ৩৫% রিফান্ড প্রদান করা হবে।"},
    "Reject cancellation? Full refund will be issued to patient.": {"bn": "বাতিল প্রত্যাখ্যান করবেন? রোগীকে সম্পূর্ণ রিফান্ড প্রদান করা হবে।"},
    "Mark as visited": {"bn": "পরিদর্শন হিসেবে চিহ্নিত করুন"},
    "Mark as missed": {"bn": "মিস হিসেবে চিহ্নিত করুন"},
    "Edit appointment": {"bn": "অ্যাপয়েন্টমেন্ট সম্পাদনা"},
    "Request Cancellation": {"bn": "বাতিলের অনুরোধ"},
    "Cancel Appointment": {"bn": "অ্যাপয়েন্টমেন্ট বাতিল"},
    "Edit Booking": {"bn": "বুকিং সম্পাদনা"},
    "Mark as visited": {"bn": "পরিদর্শন"},
    "Mark as missed": {"bn": "মিস"},
    "Approve": {"bn": "অনুমোদন"},
    "Reject": {"bn": "প্রত্যাখ্যান"},
    "Save Changes": {"bn": "পরিবর্তন সংরক্ষণ করুন"},
    "Payment successful! Appointment confirmed. Receipt generated.": {"bn": "পেমেন্ট সফল! অ্যাপয়েন্টমেন্ট নিশ্চিত। রসিদ তৈরি হয়েছে।"},
    "Appointment booked successfully": {"bn": "অ্যাপয়েন্টমেন্ট সফলভাবে বুক করা হয়েছে"},
    "Please select date and time.": {"bn": "অনুগ্রহ করে তারিখ এবং সময় নির্বাচন করুন।"},
    "This time slot is already booked. Please choose another.": {"bn": "এই সময় স্লট ইতিমধ্যে বুক করা আছে। অনুগ্রহ করে অন্য একটি নির্বাচন করুন।"},
    "Only patients can book appointments.": {"bn": "শুধুমাত্র রোগীরা অ্যাপয়েন্টমেন্ট বুক করতে পারেন।"},
    "Only patients can view appointments.": {"bn": "শুধুমাত্র রোগীরা অ্যাপয়েন্টমেন্ট দেখতে পারেন।"},
    "Only pending or confirmed appointments can be edited.": {"bn": "শুধুমাত্র অপেক্ষাম Rowe বা নিশ্চিত অ্যাপয়েন্টমেন্ট সম্পাদনা করা যায়।"},
    "You have reached the maximum of 3 edits for this booking.": {"bn": "আপনি এই বুকিংয়ের জন্য সর্বোচ্চ ৩টি সম্পাদনা করেছেন।"},
    "Appointments can only be edited at least 4 hours before the scheduled time.": {"bn": "অ্যাপয়েন্টমেন্টগুলি শুধুমাত্র নির্ধারিত সময়ের কমপক্ষে ৪ ঘণ্টা আগে সম্পাদনা করা যায়।"},
    "Please select both date and time.": {"bn": "অনুগ্রহ করে উভয় তারিখ এবং সময় নির্বাচন করুন।"},
    "Doctor is not available on this day.": {"bn": "ডাক্তার এই দিনে উপলব্ধ নন।"},
    "No available slots at the moment.": {"bn": "মুদ্র Guine última স্লট নেই।"},
    "Appointment updated successfully.": {"bn": "অ্যাপয়েন্টমেন্ট সফলভাবে আপডেট হয়েছে।"},
    "This appointment cannot be cancelled.": {"bn": "এই অ্যাপয়েন্টমেন্ট বাতিল করা যায় না।"},
    "Cancellation request sent to doctor for approval. You will be notified once decided.": {"bn": "বাতিলের অনুরোধ ডাক্তারের অনুমোদনের জন্য পাঠানো হয়েছে। সিদ্ধান্ত নিলে আপনাকে জানানো হবে।"},
    "Appointment cancelled.": {"bn": "অ্যাপয়েন্টমেন্ট বাতিল হয়েছে।"},
    "refunded": {"bn": "রিফান্ড করা হয়েছে"},
    "Cancellation confirmed": {"bn": "বাতিল নিশ্চিত"},
    "Cancellation request sent": {"bn": "বাতিলের অনুরোধ পাঠানো হয়েছে"},
    "Appointment rescheduled by patient": {"bn": "রোগীর দ্বারা অ্যাপয়েন্টমেন্ট পুনরায় সময়সূচি করা হয়েছে"},
    "Appointment updated": {"bn": "অ্যাপয়েন্টমেন্ট আপডেট হয়েছে"},
    "View Profile Details": {"bn": "প্রোফাইল তথ্য দেখুন"},
    "BMDC Doctor Verification Pending": {"bn": "বিএমডিসি ডাক্তার ভেরিফিকেশন প্রক্রিয়াধীন"},
    "Identity Verification Pending": {"bn": "পরিচয়পত্র ভেরিফিকেশন প্রক্রিয়াধীন"},
    "Your uploaded BMDC License Document is currently being reviewed by CareBridge Admin. For safety & medical compliance, active doctor tools (prescriptions & booking) will unlock as soon as your document is approved.": {"bn": "আপনার আপলোডকৃত বিএমডিসি লাইসেন্স নথিটি কেয়ারব্রিজ অ্যাডমিন কর্তৃক পর্যালোচনা করা হচ্ছে। নিরাপত্তার কারণে অ্যাকাউন্ট ভেরিফাইড না হওয়া পর্যন্ত প্রেসক্রিপশন এবং রোগী দেখা সুবিধাটি স্থগিত থাকবে।"},
    "Your uploaded identity document is being reviewed by CareBridge Admin. Verified BD identity ensures safety for offline in-person chamber consultations.": {"bn": "আপনার আপলোডকৃত জাতীয় পরিচয়পত্র/জন্ম সনদটি অ্যাডমিন পর্যালোচনা করছেন। অফলাইন অ্যাপয়েন্টমেন্ট নিরাপত্তার জন্য ভেরিফিকেশন আবশ্যক।"},
    "Log out": {"bn": "লগ আউট"},
    "Helping patients understand and follow their prescriptions after they leave the doctor's office.": {"bn": "রোগীদের প্রেসক্রিপশন বুঝতে এবং ঠিকমতো অনুসরণ করতে সাহায্য করে।"},
    "Quick Navigation": {"bn": "দ্রুত নেভিগেশন"},
    "Patient Dashboard": {"bn": "রোগীর ড্যাশবোর্ড"},
    "Prescription History": {"bn": "প্রেসক্রিপশন ইতিহাস"},
    "Today's Dose Schedule": {"bn": "আজকের ওষুধের তালিকা"},
    "Doctor Follow-ups": {"bn": "ডাক্তার ফলো-আপ"},
    "Doctor Dashboard": {"bn": "ডাক্তার ড্যাশবোর্ড"},
    "Patient Directory": {"bn": "রোগী ডিরেক্টরি"},
    "Prescription Activity Log": {"bn": "প্রেসক্রিপশন কার্যকলাপ লগ"},
    "Doctor Notifications": {"bn": "ডাক্তার নোটিফিকেশন"},
    "Account & Support": {"bn": "অ্যাকাউন্ট ও সহায়তা"},
    "My Profile Settings": {"bn": "প্রোফাইল সেটিংস"},
    "Alerts & Notifications": {"bn": "নোটিফিকেশন"},
    "Edit Doctor Profile": {"bn": "ডাক্তার প্রোফাইল এডিট"},
    "Create account": {"bn": "অ্যাকাউন্ট তৈরি করুন"},
    "Built as a practicum project.": {"bn": "একটি প্র্যাকটিকাম প্রকল্প হিসেবে তৈরি।"},
    "Manage Schedule": {"bn": "সময়সূচী পরিচালনা"},
    "Appointments": {"bn": "অ্যাপয়েন্টমেন্ট"},
    "Export Report": {"bn": "রিপোর্ট এক্সপোর্ট"},
    "No patients yet": {"bn": "এখনও কোনো রোগী নেই"},
    "Your patient list will appear here after you issue prescriptions.": {"bn": "প্রেসক্রিপশন জারি করার পর আপনার রোগীর তালিকা এখানে প্রদর্শিত হবে।"},
    "Search by name or phone number": {"bn": "নাম বা ফোন নম্বর দিয়ে অনুসন্ধান করুন"},
    "Phone": {"bn": "ফোন"},
    "District": {"bn": "জেলা"},
    "No patients found.": {"bn": "কোনো রোগী পাওয়া যায়নি।"},
    "View File →": {"bn": "ফাইল দেখুন →"},
    "No appointments found.": {"bn": "কোনো অ্যাপয়েন্টমেন্ট পাওয়া যায়নি।"},
    "Total": {"bn": "মোট"},
    "Pending": {"bn": "অপেক্ষাম Rowe"},
    "Confirmed": {"bn": "নিশ্চিত"},
    "Visited": {"bn": "পরিদর্শন"},
    "Missed": {"bn": "মিস"},
    "Cancelled": {"bn": "বাতিল"},
    "Pending Approval": {"bn": "অনুমোদনের অপেক্ষায়"},
    "Today": {"bn": "আজ"},
    "Auto-Detect Missed": {"bn": "অটো-ডিটেক্ট মিস"},
    "Appointment Report": {"bn": "অ্যাপয়েন্টমেন্ট রিপোর্ট"},
    "Export Financial Report": {"bn": "আর্থিক রিপোর্ট এক্সপোর্ট"},
    "Emergency Alert": {"bn": "জরুরি সতর্কতা"},
    "No appointments found.": {"bn": "কোনো অ্যাপয়েন্টমেন্ট পাওয়া যায়নি।"},
    "Mark as visited": {"bn": "পরিদর্শন হিসেবে চিহ্নিত করুন"},
    "Mark as missed": {"bn": "মিস হিসেবে চিহ্নিত করুন"},
    "Manage": {"bn": "পরিচালনা"},
    "Patient Rules": {"bn": "রোগীর নিয়ম"},
    "Doctor Rules": {"bn": "ডাক্তারের নিয়ম"},
    "Rules & Guidelines": {"bn": "নিয়ম ও নির্দেশিকা"},
    "Please follow these rules to ensure a safe and effective experience on CareBridge AI.": {"bn": "CareBridge AI-তে সুরক্ষিত ও কার্যকর অভিজ্ঞতা নিশ্চিত করতে অনুগ্রহ করে এই নিয়মগুলি অনুসরণ করুন।"},
    "Patient Compliance Rules": {"bn": "রোগীর অনুসরণযোগ্য নিয়ম"},
    "Doctor Compliance Rules": {"bn": "ডাক্তারের অনুসরণযোগ্য নিয়ম"},
    "1. Provide accurate health information": {"bn": "১. সঠিক স্বাস্থ্য তথ্য প্রদান করুন"},
    "2. Follow prescribed dosage and schedule": {"bn": "২. নির্দিষ্ট ডোজ এবং সময়সূচী অনুসরণ করুন"},
    "3. Attend follow-up appointments": {"bn": "৩. ফলো-আপ অ্যাপয়েন্টমেন্টে উপস্থিত থাকুন"},
    "4. Inform doctor of any side effects": {"bn": "৪. যেকোনো পার্শ্বপ্রতিক্র্যা সম্পর্কে ডাক্তারকে জানান"},
    "5. Keep your profile updated": {"bn": "৫. আপনার প্রোফাইল আপডেট রাখুন"},
    "6. Cancel appointments at least 24 hours in advance": {"bn": "৬. অ্যাপয়েন্টমেন্টগুলি কমপক্ষে ২৪ ঘণ্টা আগে বাতিল করুন"},
    "7. Use the platform respectfully": {"bn": "৭. প্ল্যাটফর্মটি সন্মানসorge ব্যবহার করুন"},
    "8. Do not share prescription medications": {"bn": "৮. প্রেসক্রিপশন ওষুধ শেয়ার করবেন না"},
    "1. Verify patient identity before consultation": {"bn": "১. পরামর্শের আগে রোগীর পরিচয় যাচাই করুন"},
    "2. Provide accurate diagnoses and prescriptions": {"bn": "২. সঠিক রোগ নির্ণয় ও প্রেসক্রিপশন প্রদান করুন"},
    "3. Maintain patient confidentiality": {"bn": "৩. রোগীর গোপনীয়তা বজায় রাখুন"},
    "4. Update patient records promptly": {"bn": "৪. রোগীর রেকর্ড দ্রুত আপডেট করুন"},
    "5. Respond to appointment requests in a timely manner": {"bn": "৫. সময়মতো অ্যাপয়েন্টমেন্ট অনুরোধের উত্তর দিন"},
    "6. Follow medical guidelines and best practices": {"bn": "৬. চিকিৎসা নির্দেশিকা ও সেরা পদ্ধতিতে অনুসরণ করুন"},
    "7. Do not prescribe controlled substances without proper examination": {"bn": "৭. নির্দিষ্ট পরীক্ষা ছাড়া নিয়ন্ত্রিত পদার্থ প্রেসক্রিপশন করবেন না"},
    "8. Keep your professional credentials updated": {"bn": "৮. আপনার পেশাগত পরিচয়পত্র আপডেট রাখুন"},
    "Warning": {"bn": "সতর্কতা"},
    "Are you sure?": {"bn": "আপনি নিশ্চিত?"},
    "This action cannot be undone.": {"bn": "এই কর্মটি বাতিল করা যাবে না।"},
    "Confirm": {"bn": "নিশ্চিত করুন"},
    "Cancel": {"bn": "বাতিল"},
    "Previous": {"bn": "পূর্ববর্তী"},
    "Next": {"bn": "পরবর্তী"},
    "Page": {"bn": "পৃষ্ঠা"},
    "of": {"bn": "এর"},
    "Showing": {"bn": "দেখানো হচ্ছে"},
    "to": {"bn": "থেকে"},
    "results": {"bn": "ফলাফল"},
    "Overall Report": {"bn": "ওভারঅল রিপোর্ট"},
    "Patient List": {"bn": "রোগী তালিকা"},
    "Schedule": {"bn": "সময়সূচী"},
    "History": {"bn": "ইতিহাস"},
    "Notifications": {"bn": "বিজ্ঞপ্তি"},
    "Rules": {"bn": "নিয়মাবলী"},
    "Book Now": {"bn": "বুক করুন"},
    "Book Appointment": {"bn": "অ্যাপয়েন্টমেন্ট বুক করুন"},
    "Personal Information": {"bn": "ব্যক্তিগত তথ্য"},
    "Date of Birth": {"bn": "জন্ম তারিখ"},
    "Gender": {"bn": "লিঙ্গ"},
    "Age": {"bn": "বয়স"},
    "All Patients": {"bn": "সকল রোগী"},
    "Search Doctors": {"bn": "ডাক্তার খুঁজুন"},
    "Find Top Doctors in Bangladesh": {"bn": "বাংলাদেশের সেরা ডাক্তারদের খুঁজুন"},
    "Specialty": {"bn": "বিশেষত্ব"},
    "Years Experience": {"bn": "বছরের অভিজ্ঞতা"},
    "Consultation Fee": {"bn": "পরামর্শ ফি"},
    "Experience": {"bn": "অভিজ্ঞতা"},
    "Chamber": {"bn": "চেম্বার"},
    "Online Video": {"bn": "অনলাইন ভিডিও"},
    "Emergency Scanner": {"bn": "জরুরী স্ক্যানার"},
    "AI Health Scanner": {"bn": "এআই হেলথ স্ক্যানার"},
    "Upload Photo": {"bn": "ছবি আপলোড করুন"},
    "Analyze": {"bn": "বিশ্লেষণ করুন"},
    "Medical History": {"bn": "মেডিকেল ইতিহাস"},
    "Health Journey": {"bn": "স্বাস্থ্য যাত্রা"},
    "Timeline": {"bn": "টাইমলাইন"},
    "No Records": {"bn": "কোনো রেকর্ড নেই"},
    "Clear All": {"bn": "সব মুছুন"},
}


@register.simple_tag(takes_context=True)
def translate_bn(context, text):
    if not text:
        return ""
    site_lang = None
    if isinstance(context, dict) or hasattr(context, "get"):
        site_lang = context.get("site_lang")
        if not site_lang:
            req = context.get("request")
            if req and hasattr(req, "session"):
                site_lang = req.session.get("site_lang")

    if not site_lang:
        try:
            from django.utils.translation import get_language
            curr = get_language()
            if curr and curr.startswith("bn"):
                site_lang = "bn"
        except Exception:
            pass

    if site_lang == "bn":
        translated = TRANSLATIONS.get(str(text).strip(), {}).get("bn")
        if translated:
            return mark_safe(translated)
    return text


@register.filter(name='t')
def translate_filter(text):
    if not text:
        return ""
    try:
        from django.utils.translation import get_language
        curr = get_language()
        if curr and curr.startswith("bn"):
            translated = TRANSLATIONS.get(str(text).strip(), {}).get("bn")
            if translated:
                return mark_safe(translated)
    except Exception:
        pass
    return text


@register.filter(name='render_ai_advice')
def render_ai_advice(text):
    """
    Renders AI medical advice text into clean, beautiful HTML:
    - Strips and formats markdown bold (**bold**) into styled <strong> elements
    - Formats bullet points (inline or newline) into clean lists
    - Removes all raw '**' and stray asterisks
    - Formats headers and paragraphs cleanly
    """
    if not text:
        return ""

    import re
    from django.utils.html import escape

    # Escape HTML to prevent injection
    val = escape(str(text))

    # Convert markdown bold **text** to strong
    val = re.sub(r'\*\*(.*?)\*\*', r'<strong class="font-bold text-stone-900 dark:text-stone-100">\1</strong>', val)
    # Remove any rogue ** or standalone *
    val = val.replace("**", "").replace("__", "")

    # If bullets are inline separated by " • ", break them into newlines
    val = re.sub(r'\s*•\s*', '\n• ', val)

    # Separate common section headers (e.g. . 👨‍⚕️) into newlines
    val = re.sub(r'([.!?।])\s*(👨‍⚕️|💡|📋|📅|💊|🔬|🩺|ℹ️|✅|⚠️|👋)', r'\1\n\2', val)

    lines = [line.strip() for line in val.splitlines() if line.strip()]
    if not lines:
        return ""

    html_parts = []
    in_list = False

    for line in lines:
        if line.startswith("• ") or line.startswith("- "):
            item_text = line[2:].strip()
            if not in_list:
                html_parts.append('<ul class="my-2.5 space-y-2 pl-1">')
                in_list = True
            html_parts.append(
                f'<li class="flex items-start gap-2 text-xs text-stone-800 dark:text-stone-200">'
                f'<span class="text-teal-600 dark:text-teal-400 font-bold shrink-0 mt-0.5">•</span>'
                f'<span class="leading-relaxed">{item_text}</span>'
                f'</li>'
            )
        else:
            if in_list:
                html_parts.append('</ul>')
                in_list = False

            if any(emoji in line for emoji in ["👨‍⚕️", "💡", "📋", "📅", "💊", "🔬", "🩺", "ℹ️", "✅", "⚠️", "👋"]):
                html_parts.append(
                    f'<div class="font-semibold text-xs text-teal-950 dark:text-teal-300 mt-3 mb-1.5 flex items-center gap-1.5">'
                    f'{line}'
                    f'</div>'
                )
            else:
                html_parts.append(f'<p class="text-xs text-stone-800 dark:text-stone-200 leading-relaxed mb-2">{line}</p>')

    if in_list:
        html_parts.append('</ul>')

    return mark_safe("".join(html_parts))


