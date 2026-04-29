import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';

@Injectable({
  providedIn: 'root',
})
export class ModeService {
  private editModeSource = new BehaviorSubject<boolean>(false);
  editMode$ = this.editModeSource.asObservable();

  private finalizedModeSource = new BehaviorSubject<boolean>(false);
  finalizedMode$ = this.finalizedModeSource.asObservable();

  constructor() {}

  setEditMode(isEdit: boolean) {
    this.editModeSource.next(isEdit);
  }

  setFinalizedMode(isFinalized: boolean) {
    this.finalizedModeSource.next(isFinalized);
  }
}
