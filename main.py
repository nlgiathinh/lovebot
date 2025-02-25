import discord
from discord.ext import commands
from discord.ui import Button, View
from PIL import Image, ImageFilter, ImageDraw, ImageFont
import io
import random
from datetime import datetime
import asyncpg
from io import BytesIO
import unicodedata
import asyncio
import os
from dotenv import load_dotenv
 
# Load environment variables
load_dotenv()
# Bot setup  
intents = discord.Intents.default()  
intents.message_content = True  
bot = commands.Bot(command_prefix=".", intents=intents)  

# Database setup  
# Modified database setup
# Database setup  
async def setup_database():
    try:
        # Get DATABASE_URL from environment variable
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            raise ValueError("No DATABASE_URL environment variable found")
        
        # Create connection pool
        bot.db = await asyncpg.create_pool(database_url)
        print("Connected to PostgreSQL database!")
        
        # Create tables
        async with bot.db.acquire() as conn:  # Changed from bot.conn to bot.db
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS cards (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    date TEXT,
                    series TEXT,
                    image BYTEA,
                    notes TEXT,
                    series_emoji TEXT
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS inventory (
                    user_id BIGINT,
                    card_id TEXT,
                    quantity INTEGER,
                    grabbed_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, card_id),
                    FOREIGN KEY (card_id) REFERENCES cards(id)
                )
            ''')
            print("Database tables created/verified!")
            
    except Exception as e:
        print(f"Database setup error: {str(e)}")
        raise

@bot.event  
async def on_ready():  
    print(f'Bot is ready as {bot.user}')  
    await setup_database()




#___________________________________________________________Drop & Grab___________________________________________________________
class CardButton(discord.ui.Button):  
    def __init__(self, index, card_data):  
        super().__init__(style=discord.ButtonStyle.primary, label=str(index + 1))  
        self.card_data = card_data  

    async def callback(self, interaction: discord.Interaction):  
        user_id = interaction.user.id  
        card_id = self.card_data['id']  
        
        # Change this button's style to green  
        self.style = discord.ButtonStyle.success  
        
        # Disable all buttons in the view  
        for item in self.view.children:  
            item.disabled = True  
        
        async with bot.db.acquire() as conn:  
            await conn.execute('''  
                INSERT INTO inventory (user_id, card_id, quantity, grabbed_time)  
                VALUES ($1, $2, 1, CURRENT_TIMESTAMP)  
                ON CONFLICT(user_id, card_id) DO UPDATE SET   
                quantity = quantity + 1,  
                grabbed_time = CURRENT_TIMESTAMP  
            ''', user_id, card_id)  
            await conn.commit()  

        # Update the message with disabled buttons  
        await interaction.response.edit_message(view=self.view)  
        
        # Send the grab confirmation message  
        await interaction.followup.send(  
            f"{interaction.user.mention} Em iu đã nhặt được thẻ **{self.card_data['name']}**  💕"  
        )

@bot.command(aliases=['d'])  
#@commands.cooldown(1, 120, commands.BucketType.user)  # 1 use every 120 seconds (2 minutes)
async def drop(ctx):  
    async with bot.db.acquire() as conn:  
        cursor = await conn.execute('SELECT * FROM cards')  
        all_cards = await cursor.fetchall()  
        
    if len(all_cards) < 3:  
        await ctx.send("Not enough cards in the database!")  
        return  
        
    selected_cards = random.sample(all_cards, 3)  
    images = []  
    card_data = []  
    
    for card in selected_cards:  
        img = Image.open(BytesIO(card[4]))  # card[4] is the image blob  
        img = img.resize((int(img.width * 500/img.height), 500))  
        images.append(img)  
        card_data.append({  
            'id': card[0],  
            'name': card[1],  
            'date': card[2],  
            'series': card[3],  
            'notes': card[5]  
        })  

    # Combine images  
    total_width = sum(img.width for img in images) + 40  # 20px spacing between images  
    max_height = 500  
    
    combined = Image.new('RGBA', (total_width, max_height), (0, 0, 0, 0))  
    x_offset = 0  
    
    for img in images:  
        combined.paste(img, (x_offset, 0))  
        x_offset += img.width + 20  

    # Save combined image  
    with BytesIO() as image_binary:  
        combined.save(image_binary, 'PNG')  
        image_binary.seek(0)  
        
        # Create view with buttons  
        view = discord.ui.View()  
        for i in range(3):  
            view.add_item(CardButton(i, card_data[i]))  
            
        file = discord.File(fp=image_binary, filename='cards.png')  
        await ctx.send(file=file, view=view)
@drop.error  
async def drop_error(ctx, error):  
    if isinstance(error, commands.CommandOnCooldown):  
        remaining_time = int(error.retry_after)  
        minutes = remaining_time // 60  
        seconds = remaining_time % 60  
        await ctx.send(f"Drop is on cooldown! Try again in {minutes}m {seconds}s")



#_______________________________________________________________________INVENTORY_______________________________________________________________________
import discord  
from discord.ext import commands  
from discord.ui import View, Button  
import aiosqlite  
from datetime import datetime  

class PaginationView(View):  
    def __init__(self, inventory_list):  
        super().__init__(timeout=60)  
        self.inventory_list = inventory_list  
        self.current_page = 0  
        self.items_per_page = 10  
        self.total_pages = len(inventory_list) // self.items_per_page + (1 if len(inventory_list) % self.items_per_page else 0)  
        
        # Add buttons  
        self.add_item(Button(label="◀", custom_id="previous", style=discord.ButtonStyle.primary))  
        self.add_item(Button(label="▶", custom_id="next", style=discord.ButtonStyle.primary))  

    def get_current_page_embed(self, author_name):  
        start_idx = self.current_page * self.items_per_page  
        end_idx = start_idx + self.items_per_page  
        current_items = self.inventory_list[start_idx:end_idx]  

        embed = discord.Embed(title=f"Bộ sưu tập của {author_name} 💕", color=discord.Color.blue())  
        embed.add_field(  
            name=f"Page {self.current_page + 1}/{self.total_pages}",  
            value="\n".join(current_items) if current_items else "No items found.",  
            inline=False  
        )  
        return embed  

    async def interaction_check(self, interaction: discord.Interaction) -> bool:  
        button_id = interaction.data["custom_id"]  
        
        if button_id == "previous" and self.current_page > 0:  
            self.current_page -= 1  
        elif button_id == "next" and self.current_page < self.total_pages - 1:  
            self.current_page += 1  
        
        await interaction.response.edit_message(  
            embed=self.get_current_page_embed(interaction.user.name)  
        )  
        return True  

@bot.command(aliases=['c'])  
async def inventory(ctx):  
    async with bot.db.acquire() as conn:  
        rows = await conn.fetch('''  
            SELECT   
                cards.id,  
                inventory.quantity,  
                cards.series,  
                cards.name,  
                cards.date,  
                cards.series_emoji,   
                inventory.grabbed_time  
            FROM inventory  
            JOIN cards ON inventory.card_id = cards.id  
            WHERE inventory.user_id = $1  
            ORDER BY inventory.grabbed_time DESC  
        ''', ctx.author.id)   
        
        if not rows:  
            await ctx.send("Eiu chưa sưu tập thẻ nào cả 😭")  
            return  

        # Create inventory list  
        inventory_list = []  
        for row in rows:  
            card_id, quantity, series, name, release_date, series_emoji, grabbed_time = row  
            
            try:  
                date_obj = datetime.strptime(release_date, '%Y-%m-%d')  
                formatted_date = date_obj.strftime('%d/%m/%y')  
            except:  
                formatted_date = release_date  
            
            # Format the emoji properly if it's just an ID  
            if series_emoji and series_emoji.isdigit():  
                series_emoji = f"<:card:{series_emoji}>"  
            elif not series_emoji:  
                series_emoji = "🃏"  # Default emoji if none is set  
            
            formatted_line = f"`{quantity}x` {series_emoji} `{card_id}` {series} **{name}** `{formatted_date}`"  
            inventory_list.append(formatted_line)  

        # Create view with pagination  
        view = PaginationView(inventory_list)  
        initial_embed = view.get_current_page_embed(ctx.author.name)  
        
        await ctx.send(embed=initial_embed, view=view)
#__________________________________________________________________________VIEW CARD__________________________________________________________________________
@bot.command(aliases=['v'])  
async def view(ctx, card_id=None):  
    if not card_id:  
        await ctx.send("Please provide a card ID to view!")  
        return  

    async with bot.db.acquire() as conn:  
        owned = await conn.fetchrow('''  
            SELECT inventory.quantity   
            FROM inventory   
            WHERE inventory.user_id = $1 AND inventory.card_id = $2  
        ''', ctx.author.id, card_id)  
        
        
        if not owned:  
            await ctx.send("You must own the card to view it!")  
            return  

        row = await conn.fetchrow('''  
            SELECT cards.name,   
                cards.series,   
                cards.date,   
                cards.image,   
                cards.notes,  
                cards.series_emoji,  
                inventory.quantity  
            FROM cards  
            LEFT JOIN inventory ON cards.id = inventory.card_id   
                AND inventory.user_id = $1  
            WHERE cards.id = $2  
        ''', ctx.author.id, card_id)  
        
        
        if not row:  
            await ctx.send("Card not found!")  
            return  
            
        name, series, date, image_data, notes, series_emoji, quantity = row  
        
        # Format the emoji  
        if series_emoji and series_emoji.isdigit():  
            series_emoji = f"<:card:{series_emoji}>"  
        elif not series_emoji:  
            series_emoji = "🃏"  

        # Convert date format  
        formatted_date = datetime.strptime(date, '%Y-%m-%d').strftime('%d/%m/%Y')  

        embed = discord.Embed(color=discord.Color.blue())  
        embed.title = f"{series_emoji} {name}"  
        
        # Add fields with all inline=True except notes  
        embed.add_field(name="ID", value=f"`{card_id}`", inline=True)  
        embed.add_field(name="Series", value=series, inline=True)  
        embed.add_field(name="Release Date", value=formatted_date, inline=True)  
            
        if image_data:  
            file = discord.File(io.BytesIO(image_data), filename="card.png")  
            embed.set_image(url="attachment://card.png")  
            # Add copies owned as footer  
            embed.set_footer(text=f"Copies owned: {quantity}")  
        
        if notes:  
            embed.add_field(name="Notes", value=notes, inline=False)  
            
        if image_data:  
            await ctx.send(file=file, embed=embed)  
        else:  
            await ctx.send(embed=embed)
#__________________________________________________________________________COOLDOWN__________________________________________________________________________
@bot.command(aliases=['cd'])  
async def cooldown(ctx):  
    # Get the drop command  
    drop_command = bot.get_command('drop')  
    
    # Check if the command is on cooldown  
    if drop_command._buckets.valid:  
        bucket = drop_command._buckets.get_bucket(ctx)  
        retry_after = bucket.get_retry_after()  
        
        if retry_after:  
            minutes = int(retry_after) // 60  
            seconds = int(retry_after) % 60  
            await ctx.send(f"Drop cooldown: {minutes}m {seconds}s remaining")  
        else:  
            await ctx.send("Drop is ready!")  
    else:  
        await ctx.send("Drop is ready!")


#________________________________________________________ALBUM________________________________________________________


def normalize_vietnamese(text):  
    return unicodedata.normalize('NFC', text) 
def blob_to_image(blob_data):  
    return Image.open(io.BytesIO(blob_data))  

def create_blurred_card(image_blob, target_height):  
    # Convert blob to PIL Image  
    img = blob_to_image(image_blob)  
    if img.mode != 'RGBA':  
        img = img.convert('RGBA')  
    
    # Calculate new width while maintaining aspect ratio  
    aspect_ratio = img.width / img.height  
    new_width = int(target_height * aspect_ratio)  
    img = img.resize((new_width, target_height), Image.Resampling.LANCZOS)  
    
    # Apply heavy blur  
    blurred = img.filter(ImageFilter.GaussianBlur(radius=10))  
    
    # Darken the image  
    darker = Image.new('RGBA', blurred.size, (0, 0, 0, 128))  
    blurred = Image.alpha_composite(blurred, darker)  
    
    return blurred  

def create_collage(collected_blobs, card_ids, target_height=400):  
    spacing = 10  # Spacing between cards  
    resized_images = []  
    
    # Calculate the height needed for image plus text  
    total_height = target_height + 30  # Added 30 pixels for text  
    
    # Process each card slot (4 slots total)  
    for i in range(4):  
        if i < len(collected_blobs):  
            # Process collected card  
            img = blob_to_image(collected_blobs[i])  
            if img.mode != 'RGBA':  
                img = img.convert('RGBA')  
            
            # Resize while maintaining aspect ratio  
            aspect_ratio = img.width / img.height  
            new_width = int(target_height * aspect_ratio)  
            img = img.resize((new_width, target_height), Image.Resampling.LANCZOS)  
            
        else:  # Empty slot  
            # Create transparent placeholder  
            img = Image.new('RGBA', (int(target_height * 0.7), target_height), (0, 0, 0, 0))  
        
        resized_images.append(img)  
    
    # Calculate total width needed  
    total_width = sum(img.width for img in resized_images) + (spacing * (len(resized_images) - 1))  
    
    # Create new transparent image with extra height for text  
    collage = Image.new('RGBA', (total_width, total_height), (0, 0, 0, 0))  
    
    # Create a draw object  
    draw = ImageDraw.Draw(collage)  
    
    # Try to load a font, fall back to default if not found  
    try:  
        font = ImageFont.truetype("ggsans.ttf", 16)  # You might need to adjust the font path and size  
    except:  
        font = ImageFont.load_default()  
    
    # Paste images and add text with spacing  
    x_offset = 0  
    for idx, img in enumerate(resized_images):  
        # Paste the image  
        collage.paste(img, (x_offset, 0), img)  
        
        # Add card ID text if available  
        if idx < len(card_ids):  
            text = f"ID: {card_ids[idx]}"  
            # Calculate text position (centered under the image)  
            text_width = draw.textlength(text, font=font)  
            text_x = x_offset + (img.width - text_width) // 2  
            draw.text((text_x, target_height + 5), text, fill=(255, 255, 255), font=font)  
        
        x_offset += img.width + spacing  
    
    return collage   

@bot.command(aliases=['a'])  
async def album(ctx, *, series_keyword: str):  
    async with bot.db.acquire() as conn:  
        # Get all series first  
        cursor = await conn.execute('SELECT DISTINCT series FROM cards ORDER BY series')  
        all_series = await cursor.fetchall()  
        
        # Normalize the search keyword  
        normalized_keyword = normalize_vietnamese(series_keyword.lower())  
        
        # Filter series using normalized comparison  
        matching_series = [  
            series for series in all_series   
            if normalized_keyword in normalize_vietnamese(series[0].lower())  
        ]  
        
        if not matching_series:  
            await ctx.send(f"Không tìm thấy series nào có từ khóa '{series_keyword}' 😢")  
            return  
        
        if len(matching_series) > 1:  
            series_list = '\n'.join([f"• {series[0]}" for series in matching_series])  
            await ctx.send(f"Tìm thấy nhiều series phù hợp với từ khóa '{series_keyword}':\n{series_list}\nVui lòng chọn một series cụ thể.")  
            return  
        
        series_name = matching_series[0][0]  
        
        # Get all cards from the matched series  
        all_cards = await conn.fetch('''  
            SELECT id, image, series_emoji  
            FROM cards  
            WHERE series = $1  
            ORDER BY id  
        ''', series_name)  
        all_cards = await cursor.fetchall()  
        
        # Get user's collected cards from this series  
        collected_rows = await conn.fetch('''  
            SELECT card_id  
            FROM inventory  
            WHERE user_id = $1 AND card_id IN (  
                SELECT id FROM cards WHERE series = $2  
            )  
        ''', ctx.author.id, series_name)  
        collected_ids = [row['card_id'] for row in collected_rows]  
        collected_ids = [row[0] for row in await cursor.fetchall()]  
        
        # Calculate progress  
        total_cards = len(all_cards)  
        collected_count = len(collected_ids)  
        
        # Get series emoji  
        series_emoji = all_cards[0][2] if all_cards[0][2] else "🃏"  
        if series_emoji.isdigit():  
            series_emoji = f"<:card:{series_emoji}>"  
        
        progress = f"{series_emoji} Progress: {collected_count}/{total_cards}"  
        # Create and send embed  
        embed = discord.Embed(  
            title=f"Album {series_name}",  
            description=progress,  
            color=discord.Color.pink()  
        )  
        await ctx.send(embed=embed)
    # Group cards into sets of 4  
    for i in range(0, len(all_cards), 4):  
        group = all_cards[i:i+4]  
        group_images = []  
        group_ids = []  # Store card IDs  
        
        for card in group:  
            if card[0] in collected_ids:  # If card is collected  
                group_images.append(card[1])  # Use original image  
            else:  # If card is not collected  
                blurred = create_blurred_card(card[1], 400)  
                with io.BytesIO() as img_byte:  
                    blurred.save(img_byte, 'PNG')  
                    group_images.append(img_byte.getvalue())  
            group_ids.append(card[0])  # Add card ID to the list  
        
        collage = create_collage(group_images, group_ids, target_height=400)  
        
        # Convert collage to bytes for sending  
        with io.BytesIO() as image_binary:  
            collage.save(image_binary, 'PNG')  
            image_binary.seek(0)  
            await ctx.send(file=discord.File(fp=image_binary, filename='collage.png'))  
        


#___________________________________________________________Memories___________________________________________________________



class RevealButton(Button):  
    def __init__(self, card_info):  
        super().__init__(label="Tiết lộ", style=discord.ButtonStyle.primary)  
        self.card_info = card_info  

    async def callback(self, interaction: discord.Interaction):  
        await interaction.response.defer()  

        try:  
            # Format the date  
            try:  
                # Convert string to datetime object and then format it  
                date_obj = datetime.strptime(self.card_info['date'], '%Y-%m-%d')  # Assuming the date in DB is in YYYY-MM-DD  
                formatted_date = date_obj.strftime('%d/%m/%Y')  
            except:  
                # If date conversion fails, use the original date  
                formatted_date = self.card_info['date']  

            # Create embed with card name as title  
            embed = discord.Embed(  
                title=self.card_info['name'],  
                color=discord.Color.pink()  
            )  
            
            # Add card information fields with modified layout and formatted date  
            embed.add_field(name="ID", value=f"`{self.card_info['id']}`", inline=True)  
            embed.add_field(name="Series", value=self.card_info['series'], inline=True)  
            embed.add_field(name="Date", value=formatted_date, inline=True)  
            
            if self.card_info['notes']:  
                embed.add_field(name="Notes", value=self.card_info['notes'], inline=False)  

            # Add the image  
            if self.card_info['image']:  
                file = discord.File(io.BytesIO(self.card_info['image']), filename="card.png")  
                embed.set_image(url="attachment://card.png")  
                await interaction.edit_original_response(embed=embed, attachments=[file], view=None)  
            else:  
                await interaction.edit_original_response(embed=embed, view=None)  

        except Exception as e:  
            print(f"Error in reveal button callback: {e}")  
            await interaction.followup.send(  
                "An error occurred while revealing the card information.",  
                ephemeral=True  
            )  

class MemoriesView(View):  
    def __init__(self, card_info):  
        super().__init__(timeout=180.0)  # Added timeout of 3 minutes  
        self.add_item(RevealButton(card_info))  

@bot.command(aliases=['m'])  
async def memories(ctx):  
    try:  
        async with bot.db.acquire() as conn:  
            # Get total number of cards  
            async with conn.execute('SELECT COUNT(*) FROM cards') as cursor:  
                total_cards = await cursor.fetchone()  
                
            if total_cards[0] == 0:  
                await ctx.send("No cards found in the database.")  
                return  
                
            # Get a random card  
            async with conn.execute('''  
                SELECT id, name, date, series, image, notes, series_emoji  
                FROM cards  
                ORDER BY RANDOM()  
                LIMIT 1  
            ''') as cursor:  
                card = await cursor.fetchone()  
                
            if not card:  
                await ctx.send("Could not fetch a card.")  
                return  
                
            # Create card info dictionary  
            card_info = {  
                'id': card[0],  
                'name': card[1],  
                'date': card[2],  
                'series': card[3],  
                'image': card[4],  
                'notes': card[5],  
                'series_emoji': card[6]  
            }  

            # Create initial embed with just the card image  
            embed = discord.Embed(  
                title="Memories",   
                color=discord.Color.pink()  
            )  
            
            # Add the image to the initial embed  
            if card_info['image']:  
                file = discord.File(io.BytesIO(card_info['image']), filename="card.png")  
                embed.set_image(url="attachment://card.png")  
                view = MemoriesView(card_info)  
                await ctx.send(embed=embed, file=file, view=view)  
            else:  
                view = MemoriesView(card_info)  
                await ctx.send(embed=embed, view=view)  

    except Exception as e:  
        print(f"Error in memories command: {e}")  
        await ctx.send("An error occurred while fetching the card.")
# Run the bot  
if __name__ == "__main__":  
    token = os.getenv('DISCORD_TOKEN')  
    if not token:  
        print("Error: No token found! Make sure you have a .env file with DISCORD_TOKEN=your_token_here")  
    else:  
        print("Starting bot...")  
        bot.run(token)