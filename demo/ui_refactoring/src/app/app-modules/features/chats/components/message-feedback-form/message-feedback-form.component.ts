import { CommonModule } from '@angular/common';
import { Component, computed, EventEmitter, inject, Input, OnDestroy, OnInit, Output, signal } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { NgSelectModule } from '@ng-select/ng-select';
import { Subscription } from 'rxjs';
import { FeedbackRating } from '../../../../../_shared/constants/feedback-rating';
import { HierarchyType } from '../../../../../_shared/constants/hierarchy-type';
import { ServiceHierarchyVM } from '../../models/service-hierarchy';
import { FeedbackFormConfig, FeedbackFormData } from '../../models/message-feedabck';
import { FeedbackTag } from '../../../../../_shared/constants/feedback-tag';


@Component({
  selector: 'app-message-feedback-form',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, NgSelectModule],
  templateUrl: './message-feedback-form.component.html',
  styleUrl: './message-feedback-form.component.scss'
})
export class MessageFeedbackFormComponent implements OnInit, OnDestroy {
  @Input() messageId!: string;
  @Input() rating!: FeedbackRating;
  @Input() config: FeedbackFormConfig = {
    showComments: true,
    showTags: false,
    showCategory: false,
    showServiceHierarchy: false,
    commentsRequired: false,
    commentsPlaceholder: 'Please tell us more about your experience...',
    commentsMaxLength: 500
  };

  @Output() submit = new EventEmitter<FeedbackFormData>();
  @Output() skip = new EventEmitter<void>();

  private readonly fb = inject(FormBuilder);
  feedbackForm!: FormGroup;
  private subscriptions = new Subscription();

  readonly feedbackTag = FeedbackTag;

  // --- Cascading hierarchy state ---
  readonly selectedFunctionId = signal<number | null>(null);
  readonly selectedSubFunctionId = signal<number | null>(null);

  readonly functions = computed<ServiceHierarchyVM[]>(() =>
    this.config.serviceHierarchies ?? []
  );

  readonly subFunctions = computed<ServiceHierarchyVM[]>(() => {
    const fnId = this.selectedFunctionId();
    if (!fnId) {
      return [];
    }
    const fn = this.functions().find(f => f.id === fnId);
    return fn?.children.filter(c => c.hierarchyType === HierarchyType.SubFunction) ?? [];
  });

  readonly availableServices = computed<ServiceHierarchyVM[]>(() => {
    const subFnId = this.selectedSubFunctionId();
    const fnId = this.selectedFunctionId();

    if (subFnId) {
      const subFn = this.subFunctions().find(s => s.id === subFnId);
      return subFn?.children.filter(c => c.hierarchyType === HierarchyType.Service) ?? [];
    }

    if (fnId) {
      const fn = this.functions().find(f => f.id === fnId);
      const hasSubFunctions = fn?.children.some(c => c.hierarchyType === HierarchyType.SubFunction) ?? false;
      if (!hasSubFunctions) {
        return fn?.children.filter(c => c.hierarchyType === HierarchyType.Service) ?? [];
      }
    }

    return [];
  });

  readonly showSubFunction = computed(() => this.subFunctions().length > 0);
  readonly showService = computed(() => this.availableServices().length > 0);

  ngOnInit(): void {
    this.initForm();
  }

  private initForm(): void {
    const commentsValidators = this.config.commentsRequired
      ? [Validators.required, Validators.maxLength(this.config.commentsMaxLength || 500)]
      : [Validators.maxLength(this.config.commentsMaxLength || 500)];

    this.feedbackForm = this.fb.group({
      comments: ['', commentsValidators],
      tags: [[]],
      category: [''],
      functionId: [null],
      subFunctionId: [null],
      serviceId: [null],
    });

    // Cascade: function change → reset sub-function + service
    this.subscriptions.add(
      this.feedbackForm.get('functionId')!.valueChanges.subscribe(val => {
        const id = val ? Number(val) : null;
        this.selectedFunctionId.set(id);
        this.selectedSubFunctionId.set(null);
        this.feedbackForm.patchValue({ subFunctionId: null, serviceId: null }, { emitEvent: false });
      })
    );

    // Cascade: sub-function change → reset service
    this.subscriptions.add(
      this.feedbackForm.get('subFunctionId')!.valueChanges.subscribe(val => {
        const id = val ? Number(val) : null;
        this.selectedSubFunctionId.set(id);
        this.feedbackForm.patchValue({ serviceId: null }, { emitEvent: false });
      })
    );
  }

  get commentsControl() {
    return this.feedbackForm.get('comments');
  }

  get selectedCategory(): string {
    return this.feedbackForm?.get('category')?.value || '';
  }

  onSubmit(): void {
    if (this.feedbackForm.valid) {
      const v = this.feedbackForm.value;
      const isContentGaps = v.category === FeedbackTag.ContentGaps;
      const formData: FeedbackFormData = {
        rating: this.rating,
        comments: v.comments?.trim() || undefined,
        category: v.category || undefined,
        functionId: isContentGaps ? (v.functionId ?? undefined) : undefined,
        subFunctionId: isContentGaps ? (v.subFunctionId ?? undefined) : undefined,
        serviceId: isContentGaps ? (v.serviceId ?? undefined) : undefined,
      };
      this.submit.emit(formData);
    }
  }

  onSkip(): void {
    this.skip.emit();
  }

  selectCategory(tag: string): void {
    const current = this.feedbackForm.get('category')?.value;
    const newValue = current === tag ? '' : tag;
    this.feedbackForm.patchValue({ category: newValue });
    if (newValue !== FeedbackTag.ContentGaps) {
      this.selectedFunctionId.set(null);
      this.selectedSubFunctionId.set(null);
      this.feedbackForm.patchValue({ functionId: null, subFunctionId: null, serviceId: null }, { emitEvent: false });
    }
  }

  isCategorySelected(tag: string): boolean {
    return this.feedbackForm?.get('category')?.value === tag;
  }

  ngOnDestroy(): void {
    this.subscriptions.unsubscribe();
  }
}
