import { computed, inject, Injectable, signal } from "@angular/core";
import { ChatStore } from "./chat.store";
import { NavItem } from "../models/chat.model";
import { SidebarCodes, SidebarNames } from "../../../../_shared/constants/sidebar";
import { Router, NavigationEnd } from "@angular/router";
import { filter } from "rxjs";

@Injectable({
    providedIn: 'root',
})

export class SideBarStore {
    private chatStore = inject(ChatStore);
    private router = inject(Router);

    // Track the currently active/selected item
    activeItemId = signal<string | null>(null);
    isSuperAdmin = this.chatStore.authUser()?.isSuperAdmin || false;

    constructor() {
        // Initialize from current URL immediately
        this.syncActiveFromUrl(this.router.url);

        // Keep in sync with route changes
        this.router.events
            .pipe(filter(event => event instanceof NavigationEnd))
            .subscribe((event: NavigationEnd) => {
                this.syncActiveFromUrl(event.urlAfterRedirects || event.url);
            });
    }

    /**
     * Syncs the active sidebar item with the current URL
     */
    private syncActiveFromUrl(url: string): void {
        // Check for conversation routes
        const conversationMatch = url.match(/\/chats(?:\/(\d+))?(?:\?|$|\/)/); 
        if (url.includes('/chats')) {
            const id = conversationMatch?.[1];
            if (!id) {
                this.activeItemId.set(SidebarCodes.NewChat);
            } else {
                this.activeItemId.set(id);
                // Auto-expand the Chat History group so the active conversation is visible
                const chatHistoryItem = this.homeChildren().find(i => i.code === SidebarCodes.ChatHistory);
                chatHistoryItem?.expanded?.set(true);
            }
            return;
        }

        // Check for admin routes
        if (url.includes('/admin/dashboard')) {
            this.activeItemId.set(SidebarCodes.AdminDashboard);
                return;
        }
        
        if (url.includes('/admin/user-management')) {
            this.activeItemId.set(SidebarCodes.AdminManagement);
            return;
        }

        // No matching route - clear active state
        this.activeItemId.set(null);
    }

    conversationChild = computed<NavItem[]>(() =>
        this.chatStore.chatConversations()
            .map(conv => ({
                id: String(conv.id),
                type: 'action',
                name: conv.title,
                code: String(conv.id),
                action: () => this.chatStore.selectConversation(conv.id),
                showInSidebar: true
            } as NavItem))
    );

    homeChildren = signal<NavItem[]>([
        {
            id: SidebarCodes.NewChat,
            type: 'action',
            name: SidebarNames.NewChat,
            code: SidebarCodes.NewChat,
            action: () => this.chatStore.startNewChat(),
            icon: 'chat-outline',
            path: '/features/page/chats',
            showInSidebar: true
        },
        {
            id: SidebarCodes.ChatHistory,
            type: 'group',
            name: SidebarNames.ChatHistory,
            code: SidebarCodes.ChatHistory,
            children: this.conversationChild,
            expanded: signal(false),
            icon: 'history',
            showInSidebar: true
        },
    ]);

    chatSidebarItems = signal<NavItem[]>([
        ...this.homeChildren(),
        {
            id: SidebarCodes.AdminDashboard,
            type: 'link',
            name: SidebarNames.AdminDashboard,
            code: SidebarCodes.AdminDashboard,
            icon: 'dashboard',
            path: '/features/page/admin/dashboard',
            showInSidebar: this.isSuperAdmin
        },
        {
            id: SidebarCodes.AdminManagement,
            name: SidebarNames.AdminManagement,
            code: SidebarCodes.AdminManagement,
            type: 'link',
            icon: 'pc-check',
            path: '/features/page/admin/user-management',
            showInSidebar: this.isSuperAdmin
        }
    ]);

    /**
     * Set the active/selected item in the sidebar
     */
    setActiveItem(itemId: string): void {
        this.activeItemId.set(itemId);
    }

    /**
     * Check if an item is currently active
     */
    isActive(itemId: string): boolean {
        return this.activeItemId() === itemId;
    }

    /**
     * Handles toggling the open state of a conversation group in the sidebar. This is needed because
     * the open state is managed by the <details> element in the template, so we need to sync that with our NavItem state.
     * @param item The NavItem representing the conversation group
     * @param event The click event from the template, used to access the <details> element's open state
     */
    toggleConversation(item: NavItem, event: Event): void {
        if (!item.expanded) {
            return;
        }

        const details = event.target as HTMLDetailsElement | null;
        if (!details) {
            return;
        }

        const nextOpenState = details.open;
        if (item.expanded() !== nextOpenState) {
            item.expanded.set(nextOpenState);
        }
    }

}

