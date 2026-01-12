# bot_rcstore.py

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
import os
import asyncio
import asyncpg
from datetime import datetime
from dotenv import load_dotenv
import aiohttp

# ================= CARREGAR .ENV =================
load_dotenv()

TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMINS = list(map(int, os.getenv("ADMINS", "").split(",")))
GRUPO_TELEGRAM = int(os.getenv("GRUPO_TELEGRAM", 0))

ASAS_API_KEY = os.getenv("ASAS_API_KEY")  # Chave da API Asas
ASAS_PIX_URL = os.getenv("ASAS_PIX_URL")  # URL para criação de cobranças PIX

STATE_DEPOSITAR = "depositar_valor"

# ================= VARIAVEIS GLOBAIS =================
bonus_ativo = False
bonus_percentual = 0
bonus_valor_minimo = 0

# ================= UTIL =================
def is_admin(user_id):
    return user_id in ADMINS

async def criar_tabelas(conn):
    await conn.execute("""
    CREATE TABLE IF NOT EXISTS usuarios(
        id BIGINT PRIMARY KEY,
        nome TEXT,
        username TEXT,
        saldo NUMERIC DEFAULT 0,
        registro TIMESTAMP
    );
    """)
    await conn.execute("""
    CREATE TABLE IF NOT EXISTS compras(
        id SERIAL PRIMARY KEY,
        usuario_id BIGINT REFERENCES usuarios(id),
        produto TEXT,
        preco NUMERIC,
        login TEXT,
        senha TEXT,
        data TIMESTAMP
    );
    """)
    await conn.execute("""
    CREATE TABLE IF NOT EXISTS estoque(
        id SERIAL PRIMARY KEY,
        produto TEXT,
        login TEXT,
        senha TEXT,
        imagens TEXT[]
    );
    """)
    await conn.execute("""
    CREATE TABLE IF NOT EXISTS bonus(
        id SERIAL PRIMARY KEY,
        ativo BOOLEAN,
        percentual NUMERIC,
        valor_minimo NUMERIC
    );
    """)

async def safe_edit_message(query, texto, teclado=None, parse_mode="Markdown"):
    try:
        await query.edit_message_text(texto, reply_markup=teclado, parse_mode=parse_mode)
    except:
        await query.message.reply_text(texto, reply_markup=teclado, parse_mode=parse_mode)

# ================= BOT MENUS =================
async def start_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn: asyncpg.Connection = context.bot_data["db"]

    usuario = await conn.fetchrow("SELECT * FROM usuarios WHERE id=$1", user.id)
    if not usuario:
        await conn.execute(
            "INSERT INTO usuarios(id,nome,username,saldo,registro) VALUES($1,$2,$3,$4,$5)",
            user.id, user.full_name, user.username or "", 0, datetime.now()
        )

    teclado = InlineKeyboardMarkup([ 
        [InlineKeyboardButton("🛒 Loja", callback_data="menu_loja")],
        [InlineKeyboardButton("💰 Saldo", callback_data="menu_saldo")],
        [
            InlineKeyboardButton("📦 Meus pedidos", callback_data="menu_pedidos"),
            InlineKeyboardButton("👤 Perfil", callback_data="menu_perfil")
        ],
        [InlineKeyboardButton("🆘 Suporte", callback_data="menu_suporte")]
    ])

    texto = (
        f"👋 Olá, *{user.full_name}*\n\n"
        "💻🔥 ®RC STORE – BOT OFICIAL ®🔥💻\n\n"
        "Bem-vindo à maior plataforma de produtos digitais!"
    )

    url_img = "https://i.postimg.cc/Gt47J7p0/Screenshot-1.png"

    if update.message:
        await update.message.reply_photo(
            photo=url_img,
            caption=texto,
            reply_markup=teclado,
            parse_mode="Markdown"
        )
    else:
        query = update.callback_query
        await query.answer()
        await query.edit_message_media(
            media=InputMediaPhoto(
                media=url_img,
                caption=texto,
                parse_mode="Markdown"
            ),
            reply_markup=teclado
        )

# ================= CALLBACK HANDLER =================
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    conn: asyncpg.Connection = context.bot_data["db"]
    data = query.data

    if data == "menu_loja":
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("📁 Produtos", callback_data="cat_produtos")],
            [InlineKeyboardButton("🔙 Voltar", callback_data="voltar_inicio")]
        ])
        await safe_edit_message(query, "Escolha uma categoria para ver os produtos disponíveis:", teclado)
        return

    if data == "cat_produtos":
        produtos = await conn.fetch("SELECT DISTINCT produto FROM estoque")
        teclado = []
        for p in produtos:
            quantidade = await conn.fetchval("SELECT COUNT(*) FROM estoque WHERE produto=$1", p["produto"])
            teclado.append([InlineKeyboardButton(f"{p['produto']} ({quantidade})", callback_data=f"comprar_{p['produto']}")])
        teclado.append([InlineKeyboardButton("🔙 Voltar", callback_data="menu_loja")])
        await safe_edit_message(query, "📦 Produtos disponíveis:", InlineKeyboardMarkup(teclado))
        return

    if data.startswith("comprar_"):
        produto = data.split("_",1)[1]
        u = await conn.fetchrow("SELECT * FROM usuarios WHERE id=$1", user.id)
        item = await conn.fetchrow("SELECT * FROM estoque WHERE produto=$1 ORDER BY id ASC LIMIT 1", produto)
        if not item:
            await safe_edit_message(query, "❌ Estoque insuficiente.")
            return

        preco = 100  # Ajuste preço por produto se quiser

        if u["saldo"] < preco:
            await safe_edit_message(query, "❌ Saldo insuficiente para a compra.")
            return

        await conn.execute("DELETE FROM estoque WHERE id=$1", item["id"])
        await conn.execute("UPDATE usuarios SET saldo=saldo-$1 WHERE id=$2", preco, user.id)
        await conn.execute(
            "INSERT INTO compras(usuario_id,produto,preco,login,senha,data) VALUES($1,$2,$3,$4,$5,$6)",
            user.id, produto, preco, item["login"], item["senha"], datetime.now()
        )

        await safe_edit_message(query, f"✅ Compra realizada!\nProduto: {produto}\nPreço: R$ {preco:.2f}")
        return

    if data == "menu_saldo":
        u = await conn.fetchrow("SELECT * FROM usuarios WHERE id=$1", user.id)
        texto = f"💰 Seu saldo: R$ {u['saldo']:.2f}\n⚡ Recarregue via PIX!"
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Adicionar saldo", callback_data="adicionar_saldo")],
            [InlineKeyboardButton("🔙 Voltar", callback_data="voltar_inicio")]
        ])
        await safe_edit_message(query, texto, teclado)
        return

    if data == "adicionar_saldo":
        context.user_data[STATE_DEPOSITAR] = True
        await query.message.reply_text("Digite o valor para adicionar ao saldo (Ex: 50):")
        return

    if data == "voltar_inicio":
        await start_menu(update, context)
        return

    if data == "menu_pedidos":
        compras = await conn.fetch("SELECT * FROM compras WHERE usuario_id=$1", user.id)
        if not compras:
            texto = "📦 Você ainda não realizou nenhuma compra."
        else:
            texto = "📦 Seus pedidos:\n\n"
            for c in compras:
                texto += f"{c['produto']} - R$ {c['preco']:.2f}\nLogin: {c['login']} | Senha: {c['senha']}\nData: {c['data'].strftime('%d/%m/%Y %H:%M:%S')}\n\n"
        teclado = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="voltar_inicio")]])
        await safe_edit_message(query, texto, teclado)
        return

# ================= RECEBER VALOR =================
async def receber_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn: asyncpg.Connection = context.bot_data["db"]

    if STATE_DEPOSITAR in context.user_data:
        try:
            valor = float(update.message.text)
            # Criar cobrança PIX no Asas
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Content-Type": "application/json",
                    "access-token": ASAS_API_KEY
                }
                payload = {
                    "amount": valor,
                    "description": f"Depósito RC Store - {user.id}",
                    "external_reference": str(user.id)
                }
                async with session.post(ASAS_PIX_URL, json=payload, headers=headers) as resp:
                    data = await resp.json()
                    if resp.status == 201:
                        pix_qrcode = data["pix"]["qrcode"]
                        await update.message.reply_text(f"✅ Cobrança PIX gerada!\n\nQRCODE: `{pix_qrcode}`", parse_mode="Markdown")
                    else:
                        await update.message.reply_text("❌ Erro ao gerar PIX. Tente novamente.")
        except:
            await update.message.reply_text("❌ Valor inválido.")
        finally:
            context.user_data.pop(STATE_DEPOSITAR, None)
        return

# ================= COMANDOS ADMIN =================
# (Aqui vão todos os comandos administrativos que já enviei anteriormente)
# /bonus, /desativar_bonus, /add_estoque, /ver_estoque, /remover_estoque, /dar_saldo, /remover_saldo, /banir, /ver_compras
# ... (Use exatamente o código que te enviei na mensagem anterior)

# ================= MAIN =================
async def main():
    app = ApplicationBuilder().token(TOKEN).build()
    conn = await asyncpg.connect(DATABASE_URL)
    await criar_tabelas(conn)
    app.bot_data["db"] = conn

    # Comandos usuários
    app.add_handler(CommandHandler("start", start_menu))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), receber_valor))

    # Comandos admin
    app.add_handler(CommandHandler("bonus", bonus_cmd))
    app.add_handler(CommandHandler("desativar_bonus", desativar_bonus))
    app.add_handler(CommandHandler("add_estoque", add_estoque))
    app.add_handler(CommandHandler("ver_estoque", ver_estoque))
    app.add_handler(CommandHandler("remover_estoque", remover_estoque))
    app.add_handler(CommandHandler("dar_saldo", dar_saldo))
    app.add_handler(CommandHandler("remover_saldo", remover_saldo))
    app.add_handler(CommandHandler("banir", banir))
    app.add_handler(CommandHandler("ver_compras", ver_compras))

    print("🤖 Bot rodando...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
