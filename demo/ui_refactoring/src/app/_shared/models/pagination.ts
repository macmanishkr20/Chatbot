import { Observable } from 'rxjs';

export class Pagination<T> {
  _data: T[] = [];
  protected _rawData: T[] = [];

  page = 1;
  pageSize = 30;

  protected setData(data: T[]) {
    this._rawData = Object.assign([], data);
    this._data = data;
  }
}

export class PaginationAsync<T> {
  pagination: Observable<T[]> = new Observable();
  rawData: T[] = [];

  page = 1;
  pageSize = 30;

  sliceData(data: T[]) {
    if (data) {
      if (this.rawData.length === 0) {
        this.rawData = Object.assign([], data);
      }

      return data
        .map((country, i) => ({ id: i + 1, ...country }))
        .slice(
          (this.page - 1) * this.pageSize,
          (this.page - 1) * this.pageSize + this.pageSize
        );
    }
    return [];
  }
}
