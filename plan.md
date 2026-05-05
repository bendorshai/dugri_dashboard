your job is to create a telegram bot for me that helps me keep track of my callories and protein...

the bot will recieve update from me such as
שניצל וסלט
or
חזה עוץ 300 גרם. וסלט עגבניות - 200 גרם
or 
a photo of the food itself

the bot will send the data to GPT API endpoint for it to calculate: Callories, and Proetein

the bot will store basic values of the daily objective - how much callories I aim to eat in a day, and how much protein... the target values will be stored in mongoDB. 

the bot will also store a value for eating window. and notify when window is about to close. 

mongodb credentials, and gpt api credentials can be found in this projecT:
C:\code\claude_games\bdm_money_system\cash_expense_tracker

the bot will documnet every entry in this sheet:
https://docs.google.com/spreadsheets/d/1ieEKz_bimI4b4r-9b2rEUe_8G3dTw9dcxA7Eav0g5kk/edit?gid=0#gid=0

you will guide me how to create an api for google sheet for the bot to utilize.

the project should be deployed on rails. 

when eating window closes the bot will summerize the
total callories,
delta from target (over budget, or under). 
if it's under give a green check positive sign, if over, yellow alert. 
also summery of protein - if above the target, green. if below - yellow alert. 

also during the day when crossing the protein level - green check positive feedback from chat bot. same goes to callories, if over eaten - yellow alert. 

when eating window closes the bot sends to GPT a summery of everything i have eaten for the past week, and the objective of the GPT is give one liner feedback that should encourage positive change in the user. the bot will also remind the GPT it's last attempts over the last 7 days so the GPT can analyze it's feedback against the actual eating log to calculate the most efective feedback for the user. GPT will provide insights about how the user responds to feedbacks and these shuld be stored in mongo for the bot keep inform GPT on every feedback time. 


bot should also have a feature for suggestion. 
in which case - it asks GPT to help with few meal options that reach the dayly goal. for example if it's noon, and there are 700 callories left and 100 protein to eat- then it suggests 3 options for the user to eat healthy meals that reach the target (below the callory target, and above the protein tagget).

you will guide me step by step how to deploy the bot, the google api, etc... 

the bot will also know my hight and my age and weight for me to suggest target callories and target protein.

all these parameter should be editable by menus:
age, hight, weight, target protein, target callory, eating window. 

bot should speak hebrew, cheerfuly and respectfuly.

after every message from the user the bot should report the total measurements of the day, 
and add a menu for all the different options mensioned above (edit values, ask for suggestions)

another otption in the menu is to ask GPT some quesiton. the GPT will be as an eating advisor which will be given the eating history of the last week along with the question. 

timezone JERUSALEM. 
also have an option to update timezone. 

