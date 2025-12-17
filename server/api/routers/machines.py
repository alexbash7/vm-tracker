from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List
from datetime import datetime, timedelta

from database import get_db
from models import Machine, ActivityEvent
from schemas import MachineResponse, MachineUpdate

router = APIRouter(prefix="/api/machines", tags=["machines"])


@router.get("/", response_model=List[MachineResponse])
async def list_machines(
    active_only: bool = False,
    db: Session = Depends(get_db)
):
    """Список всех машин"""
    query = db.query(Machine)
    
    if active_only:
        # Считаем активной если была активность за последние 10 минут
        threshold = datetime.utcnow() - timedelta(minutes=10)
        query = query.filter(Machine.last_seen_at >= threshold)
    
    machines = query.order_by(desc(Machine.last_seen_at)).all()
    return machines


@router.get("/{machine_id}", response_model=MachineResponse)
async def get_machine(machine_id: str, db: Session = Depends(get_db)):
    """Получить информацию о машине"""
    machine = db.query(Machine).filter(Machine.machine_id == machine_id).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")
    return machine


@router.patch("/{machine_id}", response_model=MachineResponse)
async def update_machine(
    machine_id: str,
    update: MachineUpdate,
    db: Session = Depends(get_db)
):
    """Обновить информацию о машине (например, user_label)"""
    machine = db.query(Machine).filter(Machine.machine_id == machine_id).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")
    
    if update.user_label is not None:
        machine.user_label = update.user_label
    if update.machine_type is not None:
        machine.machine_type = update.machine_type
    if update.is_active is not None:
        machine.is_active = update.is_active
    
    db.commit()
    db.refresh(machine)
    return machine


@router.delete("/{machine_id}")
async def delete_machine(machine_id: str, db: Session = Depends(get_db)):
    """Удалить машину и все её события"""
    machine = db.query(Machine).filter(Machine.machine_id == machine_id).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")
    
    # Удалить все события
    db.query(ActivityEvent).filter(ActivityEvent.machine_id == machine.id).delete()
    
    # Удалить машину
    db.delete(machine)
    db.commit()
    
    return {"status": "deleted", "machine_id": machine_id}
