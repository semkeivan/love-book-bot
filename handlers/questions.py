from aiogram import Router, F
from aiogram.types import CallbackQuery

from database.crud import update_stage
from keyboards.main import after_question_keyboard, main_keyboard
from texts.messages import Q1_ANSWER, Q2_ANSWER, Q3_ANSWER, Q4_ANSWER, Q5_ANSWER

router = Router()

ANSWERS = {
    "q1": (Q1_ANSWER, "asked_q1"),
    "q2": (Q2_ANSWER, "asked_q2"),
    "q3": (Q3_ANSWER, "asked_q3"),
    "q4": (Q4_ANSWER, "asked_q4"),
    "q5": (Q5_ANSWER, "asked_q5"),
}


@router.callback_query(F.data.in_({"q1", "q2", "q3", "q4", "q5"}))
async def handle_question(callback: CallbackQuery) -> None:
    await callback.answer()  # сразу снимаем "loading" с кнопки
    answer, stage = ANSWERS[callback.data]
    await update_stage(callback.from_user.id, stage)
    await callback.message.answer(answer, reply_markup=after_question_keyboard())


@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(
        "Выбери что тебя волнует больше всего 👇",
        reply_markup=main_keyboard(),
    )
